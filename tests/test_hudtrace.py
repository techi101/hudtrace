"""Tests for hudtrace. The recorded fixture comes from hud-python's own Taskset.run
(see examples/record_job.py); the small dict traces are hand-built in the same shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hudtrace.__main__ import main
from hudtrace.model import (
    CLEAN,
    FAILED_MID_RUN,
    GRADE_ERROR,
    TRUNCATED,
    fold,
    fold_loops,
    load_traces,
    outcome,
    step_row,
    view_job,
    view_trace,
)
from hudtrace.render import render_html, render_text

FIXTURE = Path(__file__).resolve().parent.parent / "examples" / "job_traces.json"


def tool_pair(name, args, text, error=False):
    call = {"name": name, "arguments": args, "id": "c"}
    return [
        {"source": "agent", "tool_calls": [call]},
        {"source": "tool", "call": call, "result": {"content": [{"type": "text", "text": text}], "isError": error}},
    ]


def trace(steps, status="completed", score=1.0, is_error=False, slug="t", stop_reason=None):
    for i, s in enumerate(steps, start=1):
        s["step_id"] = i
    return {
        "steps": steps,
        "status": status,
        "stop_reason": stop_reason,
        "grade": {"score": score, "isError": is_error},
        "slug": slug,
    }


# ---- outcome classification (mirrors hud.eval.job.Job and the CLI summary) -------------


@pytest.mark.parametrize(
    ("status", "is_error", "stop", "expected"),
    [
        ("completed", False, "done", CLEAN),
        ("error", False, None, FAILED_MID_RUN),
        ("error", True, None, GRADE_ERROR),
        ("completed", True, None, GRADE_ERROR),
        ("completed", False, "max_steps", TRUNCATED),
    ],
)
def test_outcome(status, is_error, stop, expected):
    assert outcome(trace([], status=status, is_error=is_error, stop_reason=stop)) == expected


def test_job_reward_matches_hud_rule_and_counts_crashed_rollouts():
    job = view_job(
        "j",
        [
            trace([], score=1.0),
            trace([], status="error", score=1.0),  # crashed after the work
            trace([], status="error", score=0.0),  # crashed before
            trace([], status="error", score=0.0, is_error=True),  # grade error: excluded
        ],
    )
    assert job.reward == pytest.approx(2 / 3)
    assert len(job.by_outcome(FAILED_MID_RUN)) == 2
    assert job.clean_reward == 1.0


# ---- folding ----------------------------------------------------------------------------


def test_identical_consecutive_steps_fold_into_one_row():
    rows = [step_row({"source": "agent", "content": "thinking", "step_id": i}, i) for i in (1, 2, 3)]
    folded = fold(rows)
    assert len(folded) == 1 and folded[0].count == 3 and folded[0].span == "1-3"


def test_agent_tool_loop_folds_with_its_step_range():
    steps = tool_pair("bash", {"cmd": "ls"}, "ok")
    for _ in range(4):
        steps += tool_pair("bash", {"cmd": "tail x"}, "no such file", error=True)
    steps.append({"source": "agent", "content": "done", "done": True})
    v = view_trace(trace(steps))
    assert v.n_steps == 11
    assert [r.count for r in v.rows] == [1, 1, 4, 4, 1]
    assert [r.span for r in v.rows][2:4] == ["3-9", "4-10"]


def test_different_arguments_do_not_fold():
    steps = tool_pair("bash", {"cmd": "a"}, "1") + tool_pair("bash", {"cmd": "b"}, "1")
    assert len(view_trace(trace(steps)).rows) == 4


def test_loop_fold_keeps_failure_seen_only_in_a_later_repeat():
    rows = [step_row(s, i) for i, s in enumerate(tool_pair("t", {}, "x") * 3, start=1)]
    rows[5].failed, rows[5].failure = True, "boom"  # same signature, failure only in repeat 3
    out = fold_loops(rows)
    assert out[1].failed and out[1].failure == "boom"


# ---- first failing step -----------------------------------------------------------------


def test_first_failure_is_the_earliest_failing_step_not_the_final_crash():
    steps = tool_pair("bash", {"cmd": "ls"}, "ok")
    steps += tool_pair("bash", {"cmd": "cat missing"}, "No such file", error=True)
    steps.append({"source": "system", "error": "[agent loop] RuntimeError: gateway 403"})
    v = view_trace(trace(steps, status="error"))
    assert v.first_failure.first_step == 4
    assert v.first_failure.failure == "No such file"
    assert v.last_error == "[agent loop] RuntimeError: gateway 403"


def test_clean_trace_has_no_failure():
    v = view_trace(trace(tool_pair("bash", {}, "ok")))
    assert v.first_failure is None


def test_refusal_counts_as_failure():
    v = view_trace(trace([{"source": "agent", "refusal": "I can't help"}]))
    assert v.first_failure.failure == "refusal: I can't help"


# ---- the recorded job from hud-python ---------------------------------------------------


def test_recorded_hud_job():
    name, traces = load_traces(FIXTURE)
    job = view_job(name, traces)
    by_slug = {t.slug: t for t in job.traces}
    assert {s: t.outcome for s, t in by_slug.items()} == {
        "clean": CLEAN,
        "recovers": CLEAN,
        "loops-then-crashes": FAILED_MID_RUN,
        "crashes-early": FAILED_MID_RUN,
        "grader-broken": GRADE_ERROR,
    }
    assert job.reward == pytest.approx(0.75)  # what record_job.py printed for Job.reward
    loop = by_slug["loops-then-crashes"]
    assert loop.n_steps == 19 and len(loop.rows) == 9
    assert loop.first_failure.first_step == 6
    assert "gateway 403" in loop.last_error
    assert by_slug["recovers"].first_failure.first_step == 4


def test_load_accepts_list_and_single_trace(tmp_path):
    t = trace([])
    (tmp_path / "a.json").write_text(json.dumps([t]))
    (tmp_path / "b.json").write_text(json.dumps(t))
    assert len(load_traces(tmp_path / "a.json")[1]) == 1
    assert len(load_traces(tmp_path / "b.json")[1]) == 1
    (tmp_path / "c.json").write_text("{}")
    with pytest.raises(ValueError):
        load_traces(tmp_path / "c.json")


# ---- rendering --------------------------------------------------------------------------


def test_html_lists_failing_rollouts_first_and_escapes_text():
    job = view_job(
        "j<x>",
        [
            trace([], slug="ok"),
            trace(tool_pair("bash", {}, "<script>bad</script>", error=True), status="error", slug="bad"),
        ],
    )
    html = render_html(job)
    assert html.index("bad</span>") < html.index("ok</span>")
    assert "<script>bad" not in html and "&lt;script&gt;bad" in html
    assert "First failing step: 2" in html
    assert 'class="first"' in html


def test_text_view_flags_mid_run_failures():
    job = view_job("j", [trace([], status="error", score=1.0)])
    out = render_text(job)
    assert "failed mid-run but graded, INSIDE the mean: 1" in out


def test_cli_writes_html(tmp_path, capsys):
    out = tmp_path / "r.html"
    assert main([str(FIXTURE), "-o", str(out), "--quiet"]) == 0
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")
