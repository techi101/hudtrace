"""Read HUD traces (``Trace.model_dump(mode="json")``) and work out what a reader needs first.

Works on plain JSON, so it needs no ``hud`` install. Field names follow hud-python's
``hud.types.Trace``, ``hud.agents.types.AgentStep`` / ``ToolStep`` and ``hud.Grade``
(whose wire keys are ``score`` and ``isError``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---- outcome of one rollout -------------------------------------------------------------

CLEAN = "clean"
FAILED_MID_RUN = "failed mid-run, graded"  # status error, grade still counted in the mean
GRADE_ERROR = "grade error"  # grade.isError, left out of the mean
CANCELLED = "cancelled"
TRUNCATED = "truncated"  # finished, but a limit cut it off (stop_reason != "done")


def grade_of(trace: dict[str, Any]) -> dict[str, Any]:
    return trace.get("grade") or {}


def reward_of(trace: dict[str, Any]) -> float:
    g = grade_of(trace)
    return float(g.get("score", g.get("reward", 0.0)) or 0.0)


def grade_is_error(trace: dict[str, Any]) -> bool:
    g = grade_of(trace)
    return bool(g.get("isError", g.get("is_error", False)))


def outcome(trace: dict[str, Any]) -> str:
    """Same split as hud's CLI summary: errors vs failed mid-run vs the rest."""
    if grade_is_error(trace):
        return GRADE_ERROR
    status = trace.get("status")
    if status == "error":
        return FAILED_MID_RUN
    if status == "cancelled":
        return CANCELLED
    stop = trace.get("stop_reason")
    if stop is not None and stop != "done":
        return TRUNCATED
    return CLEAN


# ---- one step, flattened into a display row ---------------------------------------------


def _short(value: Any, limit: int = 80) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, separators=(",", ":"), sort_keys=True)
        except (TypeError, ValueError):
            value = str(value)
    flat = " ".join(value.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _result_text(result: dict[str, Any] | None) -> str:
    if not result:
        return ""
    for block in result.get("content") or []:
        if block.get("type") == "text" and block.get("text"):
            return block["text"]
        if block.get("type") == "image":
            return "[image]"
    if result.get("structuredContent") is not None:
        return _short(result["structuredContent"])
    return ""


@dataclass
class Row:
    """One step (or a run of identical consecutive steps) as the viewer shows it."""

    first_step: int
    last_step: int
    source: str
    title: str
    detail: str = ""
    failed: bool = False
    failure: str = ""
    count: int = 1
    signature: str = field(default="", repr=False)

    @property
    def span(self) -> str:
        if self.first_step == self.last_step:
            return f"{self.first_step}"
        return f"{self.first_step}-{self.last_step}"


def step_row(step: dict[str, Any], index: int) -> Row:
    """Flatten a serialized Step / AgentStep / ToolStep / task step into a Row."""
    number = step.get("step_id") or index
    source = step.get("source", "?")
    error = step.get("error")
    title, detail, signature = source, "", source
    failed, failure = bool(error), error or ""

    if source == "agent":
        calls = step.get("tool_calls") or []
        if calls:
            names = ", ".join(f"{c.get('name')}({_short(c.get('arguments'), 40)})" for c in calls)
            title = f"agent calls {names}"
            signature = "agent:" + json.dumps(
                [[c.get("name"), c.get("arguments")] for c in calls], sort_keys=True, default=str
            )
        else:
            title = "agent answers" if step.get("done") else "agent says"
            signature = "agent:text:" + _short(step.get("content"), 200)
        detail = _short(step.get("content") or step.get("reasoning"), 160)
        if step.get("refusal"):
            failed, failure = True, failure or f"refusal: {step['refusal']}"
    elif source == "tool":
        call = step.get("call") or {}
        result = step.get("result") or {}
        text = _result_text(result)
        title = f"tool {call.get('name')}({_short(call.get('arguments'), 40)})"
        detail = _short(text, 160)
        if result.get("isError"):
            failed, failure = True, failure or _short(text, 200) or "tool returned isError"
        signature = "tool:" + json.dumps(
            [call.get("name"), call.get("arguments"), bool(result.get("isError")), text],
            sort_keys=True,
            default=str,
        )
    elif source == "task":
        tc = step.get("task_call") or {}
        phase = tc.get("phase")
        title = f"task {phase} {tc.get('name') or ''}".strip()
        detail = _short(tc.get("result"), 160)
        signature = f"task:{phase}:{number}"  # never fold setup/evaluate
    else:  # user, system, subagent
        texts = [
            (m.get("content") or {}).get("text", "")
            for m in step.get("messages") or []
            if isinstance(m.get("content"), dict)
        ]
        detail = _short(" ".join(t for t in texts if t) or error, 160)
        signature = f"{source}:{number}"  # never fold
    return Row(number, number, source, title, detail, failed, failure, 1, signature)


def fold(rows: list[Row]) -> list[Row]:
    """Merge consecutive rows with the same signature into one row with a count."""
    out: list[Row] = []
    for row in rows:
        prev = out[-1] if out else None
        if prev is not None and prev.signature == row.signature:
            prev.count += 1
            prev.last_step = row.last_step
            continue
        out.append(Row(**{**row.__dict__}))
    return out


def fold_loops(rows: list[Row], max_period: int = 4) -> list[Row]:
    """Fold a repeating block of up to ``max_period`` rows (agent call -> tool result -> ...).

    A run like A B A B A B becomes one ``A B`` block with count 3. Rows already folded by
    ``fold`` keep their own count; the block count multiplies on top of it only in display.
    """
    out: list[Row] = []
    i = 0
    while i < len(rows):
        best_period, best_reps = 0, 1
        for period in range(2, max_period + 1):
            block = [r.signature for r in rows[i : i + period]]
            if len(block) < period:
                break
            reps = 1
            while [r.signature for r in rows[i + reps * period : i + (reps + 1) * period]] == block:
                reps += 1
            if reps > best_reps:
                best_period, best_reps = period, reps
        if best_reps >= 2:
            block_rows = rows[i : i + best_period]
            last = rows[i + best_reps * best_period - 1]
            for j, r in enumerate(block_rows):
                merged = Row(**{**r.__dict__})
                merged.count = r.count * best_reps
                merged.title = r.title
                merged.last_step = rows[i + (best_reps - 1) * best_period + j].last_step
                out.append(merged)
            out[-best_period].detail = (
                f"[loop x{best_reps}, steps {block_rows[0].first_step}-{last.last_step}] "
                + out[-best_period].detail
            ).strip()
            for r in out[-best_period:]:
                r.signature = f"loop:{block_rows[0].first_step}:{r.signature}"
            # a failure anywhere in the repeats should still show up on the folded row
            for k in range(best_reps * best_period):
                src = rows[i + k]
                tgt = out[len(out) - best_period + (k % best_period)]
                if src.failed and not tgt.failed:
                    tgt.failed, tgt.failure = True, src.failure
            i += best_reps * best_period
        else:
            out.append(rows[i])
            i += 1
    return out


@dataclass
class TraceView:
    index: int
    slug: str
    trace_id: str | None
    status: str | None
    stop_reason: str | None
    outcome: str
    reward: float
    answer: str
    grade_note: str
    n_steps: int
    rows: list[Row]
    first_failure: Row | None
    # Trace.error: the most recent step error, i.e. what ended a crashed rollout
    last_error: str | None = None

    @property
    def counts_in_mean(self) -> bool:
        return self.outcome != GRADE_ERROR


def first_failing(rows: list[Row]) -> Row | None:
    return next((r for r in rows if r.failed), None)


def view_trace(trace: dict[str, Any], index: int = 0) -> TraceView:
    raw = [step_row(s, i) for i, s in enumerate(trace.get("steps") or [], start=1)]
    first = first_failing(raw)
    rows = fold_loops(fold(raw))
    g = grade_of(trace)
    return TraceView(
        index=index,
        slug=trace.get("slug") or f"trace {index + 1}",
        trace_id=trace.get("trace_id"),
        status=trace.get("status"),
        stop_reason=trace.get("stop_reason"),
        outcome=outcome(trace),
        reward=reward_of(trace),
        answer=_short(trace.get("content"), 160),
        grade_note=_short(g.get("content"), 200),
        n_steps=len(raw),
        rows=rows,
        first_failure=first,
        last_error=next((s.get("error") for s in reversed(trace.get("steps") or []) if s.get("error")), None),
    )


@dataclass
class JobView:
    name: str
    traces: list[TraceView]

    @property
    def reward(self) -> float:
        """Same rule as ``hud.eval.job.Job.reward``: mean over traces whose grade isn't an error."""
        graded = [t.reward for t in self.traces if t.counts_in_mean]
        return sum(graded) / len(graded) if graded else 0.0

    def by_outcome(self, name: str) -> list[TraceView]:
        return [t for t in self.traces if t.outcome == name]

    @property
    def clean_reward(self) -> float | None:
        """Mean over clean rollouts only, so infra crashes don't move the number."""
        clean = [t.reward for t in self.traces if t.outcome in (CLEAN, TRUNCATED)]
        return sum(clean) / len(clean) if clean else None


def load_traces(path: str | Path) -> tuple[str, list[dict[str, Any]]]:
    """Accept a list of traces, ``{"traces": [...]}`` (a dumped Job), or one trace."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return Path(path).stem, data
    if isinstance(data, dict) and "traces" in data:
        return data.get("name") or Path(path).stem, data["traces"]
    if isinstance(data, dict) and "steps" in data:
        return Path(path).stem, [data]
    raise ValueError(f"{path}: expected a trace, a list of traces, or a job with 'traces'")


def view_job(name: str, traces: list[dict[str, Any]]) -> JobView:
    return JobView(name, [view_trace(t, i) for i, t in enumerate(traces)])
