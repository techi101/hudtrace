"""Build site/data.json for the live demo from real hudtrace output.

    python site/build_data.py [examples/job_traces.json] [site/data.json]

Everything the page shows comes from hudtrace.model (the same code the CLI uses),
run on the recorded job. No numbers are typed in by hand.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hudtrace.model import (  # noqa: E402
    CLEAN,
    FAILED_MID_RUN,
    GRADE_ERROR,
    load_traces,
    step_row,
    view_job,
)

MAX_STR = 400


def prune(value):
    """Drop null/empty fields and cut very long strings so the drawer stays readable."""
    if isinstance(value, dict):
        out = {k: prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, [], {}, "")}
    if isinstance(value, list):
        return [prune(v) for v in value]
    if isinstance(value, str) and len(value) > MAX_STR:
        return value[:MAX_STR] + f"... [{len(value) - MAX_STR} more chars]"
    return value


def row_dict(r) -> dict:
    return {
        "first": r.first_step,
        "last": r.last_step,
        "span": r.span,
        "source": r.source,
        "title": r.title,
        "detail": r.detail,
        "failed": r.failed,
        "failure": r.failure,
        "count": r.count,
    }


def build(src: Path) -> dict:
    name, traces = load_traces(src)
    job = view_job(name, traces)
    out_traces = []
    for t, raw in zip(job.traces, traces):
        steps = raw.get("steps") or []
        raw_rows = [row_dict(step_row(s, i)) for i, s in enumerate(steps, start=1)]
        # group the folded rows: rows produced by one loop fold share a "loop:<first>:" signature
        items, i = [], 0
        while i < len(t.rows):
            r = t.rows[i]
            if r.signature.startswith("loop:"):
                key = r.signature.split(":", 2)[1]
                block = [r]
                while i + len(block) < len(t.rows) and t.rows[i + len(block)].signature.startswith(
                    f"loop:{key}:"
                ):
                    block.append(t.rows[i + len(block)])
                lo = min(b.first_step for b in block)
                hi = max(b.last_step for b in block)
                m = re.match(r"\[loop x(\d+)", block[0].detail)
                reps = int(m.group(1)) if m else block[0].count
                items.append(
                    {
                        "kind": "loop",
                        "reps": reps,
                        "first": lo,
                        "last": hi,
                        "rows": [
                            {**row_dict(b), "detail": re.sub(r"^\[loop x\d+, steps [^\]]+\] ?", "", b.detail)}
                            for b in block
                        ],
                        "failed": any(b.failed for b in block),
                    }
                )
                i += len(block)
            else:
                kind = "repeat" if r.count > 1 else "step"
                items.append({"kind": kind, **row_dict(r)})
                i += 1
        ff = t.first_failure
        out_traces.append(
            {
                "index": t.index,
                "slug": t.slug,
                "trace_id": t.trace_id,
                "status": t.status,
                "stop_reason": t.stop_reason,
                "outcome": t.outcome,
                "counts_in_mean": t.counts_in_mean,
                "reward": t.reward,
                "answer": t.answer,
                "n_steps": t.n_steps,
                "n_rows": len(t.rows),
                "first_failure": (
                    {"step": ff.first_step, "source": ff.source, "title": ff.title, "failure": ff.failure}
                    if ff
                    else None
                ),
                "last_error": t.last_error,
                "items": items,
                "raw_rows": raw_rows,
                "steps": [prune(s) for s in steps],
                "grade": prune(raw.get("grade") or {}),
            }
        )
    mid = job.by_outcome(FAILED_MID_RUN)
    err = job.by_outcome(GRADE_ERROR)
    return {
        "source_file": src.relative_to(ROOT).as_posix() if src.is_relative_to(ROOT) else src.name,
        "synthetic_note": (
            "Synthetic data: a scripted agent (no LLM) run through hud-python's real Taskset.run + "
            "LocalRuntime. Trace format, grading and status handling are the SDK's own."
        ),
        "job": {
            "name": job.name,
            "n_rollouts": len(job.traces),
            "reward": job.reward,
            "n_in_mean": sum(1 for t in job.traces if t.counts_in_mean),
            "n_failed_mid_run": len(mid),
            "failed_mid_run_reward": sum(t.reward for t in mid),
            "n_grade_errors": len(err),
            "n_clean": len(job.by_outcome(CLEAN)),
            "clean_reward": job.clean_reward,
        },
        "traces": out_traces,
    }


def main(argv: list[str]) -> int:
    src = Path(argv[1]) if len(argv) > 1 else ROOT / "examples" / "job_traces.json"
    dst = Path(argv[2]) if len(argv) > 2 else ROOT / "site" / "data.json"
    data = build(src.resolve())
    dst.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    j = data["job"]
    print(
        f"wrote {dst}: reward {j['reward']:.3f}, {j['n_failed_mid_run']} of {j['n_in_mean']} "
        f"graded rollouts failed mid-run, {j['n_grade_errors']} grade error(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
