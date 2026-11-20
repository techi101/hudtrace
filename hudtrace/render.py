"""Terminal and static-HTML views of a JobView."""

from __future__ import annotations

from html import escape

from .model import CLEAN, FAILED_MID_RUN, GRADE_ERROR, JobView, TraceView

# ---- terminal ---------------------------------------------------------------------------


def job_summary_lines(job: JobView) -> list[str]:
    n = len(job.traces)
    mid = job.by_outcome(FAILED_MID_RUN)
    err = job.by_outcome(GRADE_ERROR)
    lines = [
        f"Job '{job.name}': {n} rollouts",
        f"  mean reward (hud Job.reward rule): {job.reward:.3f}",
    ]
    if err:
        lines.append(f"  grade errors, left out of the mean: {len(err)}")
    if mid:
        lifted = sum(t.reward for t in mid)
        lines.append(
            f"  failed mid-run but graded, INSIDE the mean: {len(mid)}"
            f" (they add {lifted:.1f} reward between them)"
        )
        clean = job.clean_reward
        if clean is not None:
            lines.append(f"  mean over clean rollouts only: {clean:.3f}")
    return lines


def trace_lines(t: TraceView) -> list[str]:
    head = f"[{t.index + 1}] {t.slug}  outcome={t.outcome}  reward={t.reward:g}  steps={t.n_steps}"
    out = [head]
    if t.first_failure is not None:
        out.append(f"    first failure at step {t.first_failure.first_step}: {t.first_failure.failure}")
    if t.last_error and t.status == "error" and t.last_error != t.first_failure.failure:
        out.append(f"    rollout ended with: {t.last_error}")
    first_failed_row = next((r for r in t.rows if r.failed), None)
    for r in t.rows:
        mark = ">>" if r is first_failed_row else ("x " if r.failed else "  ")
        times = f" x{r.count}" if r.count > 1 else ""
        line = f"  {mark} {r.span:>7}  {r.title}{times}"
        if r.detail:
            line += f"  | {r.detail}"
        out.append(line)
    return out


def render_text(job: JobView) -> str:
    parts = job_summary_lines(job)
    for t in job.traces:
        parts.append("")
        parts.extend(trace_lines(t))
    return "\n".join(parts) + "\n"


# ---- static HTML ------------------------------------------------------------------------

_CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;--card:#fff;
--ok:#1f7a4d;--warn:#a15c00;--bad:#b42318;--badbg:#fdecea;--warnbg:#fff4e0;--code:#f2f1ed}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--fg:#ecebe6;--muted:#9a9993;
--line:#2c2c29;--card:#1c1c1a;--ok:#5cc28f;--warn:#f0b44c;--bad:#f87168;--badbg:#3a1714;
--warnbg:#3a2a0d;--code:#242421}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:20px;margin:0 0 4px}.sub{color:var(--muted);margin:0 0 20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px;margin-bottom:20px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:10px 12px}
.stat b{display:block;font-size:20px;font-variant-numeric:tabular-nums}.stat span{color:var(--muted);font-size:12px}
.stat.warn{border-color:var(--warn);background:var(--warnbg)}.stat.bad{border-color:var(--bad);background:var(--badbg)}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;margin:8px 0}
summary{cursor:pointer;padding:10px 12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.pill{font-size:12px;padding:1px 8px;border-radius:999px;border:1px solid currentColor}
.o-clean{color:var(--ok)}.o-mid{color:var(--warn)}.o-err,.o-cancel{color:var(--bad)}.o-trunc{color:var(--muted)}
.slug{font-weight:600}.meta{color:var(--muted);font-size:12px;margin-left:auto;font-variant-numeric:tabular-nums}
.ff{margin:0 12px 8px;padding:8px 10px;border-left:3px solid var(--bad);background:var(--badbg);border-radius:4px}
table{width:100%;border-collapse:collapse;font-size:13px}
td{padding:5px 12px;border-top:1px solid var(--line);vertical-align:top}
td.n{color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums;width:1%}
td.src{color:var(--muted);width:1%}code{background:var(--code);padding:0 4px;border-radius:4px;overflow-wrap:anywhere}
tr.failed td{background:var(--badbg)}tr.first td{background:var(--badbg);box-shadow:inset 3px 0 var(--bad)}
.times{font-weight:600;color:var(--warn);margin-left:6px}.detail{color:var(--muted);overflow-wrap:anywhere}
.why{color:var(--bad);font-size:12px}
"""

_OUTCOME_CLASS = {
    CLEAN: "o-clean",
    FAILED_MID_RUN: "o-mid",
    GRADE_ERROR: "o-err",
    "cancelled": "o-cancel",
    "truncated": "o-trunc",
}


def _trace_html(t: TraceView) -> str:
    first_failed_row = next((r for r in t.rows if r.failed), None)
    rows = []
    for r in t.rows:
        cls = "first" if r is first_failed_row else ("failed" if r.failed else "")
        times = f'<span class="times">x{r.count}</span>' if r.count > 1 else ""
        why = f'<div class="why">{escape(r.failure)}</div>' if r.failed else ""
        rows.append(
            f'<tr class="{cls}"><td class="n">{escape(r.span)}</td>'
            f'<td class="src">{escape(r.source)}</td>'
            f"<td><code>{escape(r.title)}</code>{times}"
            f'<div class="detail">{escape(r.detail)}</div>{why}</td></tr>'
        )
    ff = ""
    if t.first_failure is not None:
        ff = (
            f'<div class="ff"><b>First failing step: {t.first_failure.first_step}</b> of {t.n_steps}'
            f" ({escape(t.first_failure.source)}) {escape(t.first_failure.failure)}"
        )
        if t.last_error and t.status == "error" and t.last_error != t.first_failure.failure:
            ff += f"<br>Rollout ended with: {escape(t.last_error)}"
        ff += "</div>"
    open_attr = " open" if t.outcome != CLEAN else ""
    folded = t.n_steps - len(t.rows)
    fold_note = f", {folded} folded" if folded > 0 else ""
    return (
        f"<details{open_attr}><summary>"
        f'<span class="pill {_OUTCOME_CLASS.get(t.outcome, "")}">{escape(t.outcome)}</span>'
        f'<span class="slug">{escape(t.slug)}</span>'
        f'<span class="meta">reward {t.reward:g} · {t.n_steps} steps{fold_note}'
        f" · status {escape(str(t.status))}</span></summary>"
        f"{ff}<table>{''.join(rows)}</table></details>"
    )


def render_html(job: JobView) -> str:
    n = len(job.traces)
    mid = job.by_outcome(FAILED_MID_RUN)
    err = job.by_outcome(GRADE_ERROR)
    stats = [f'<div class="stat"><b>{job.reward:.3f}</b><span>mean reward (Job.reward rule)</span></div>']
    stats.append(f'<div class="stat"><b>{n}</b><span>rollouts</span></div>')
    stats.append(
        f'<div class="stat{" warn" if mid else ""}"><b>{len(mid)}</b>'
        "<span>failed mid-run, still in the mean</span></div>"
    )
    stats.append(
        f'<div class="stat{" bad" if err else ""}"><b>{len(err)}</b>'
        "<span>grade errors, out of the mean</span></div>"
    )
    if mid and job.clean_reward is not None:
        stats.append(
            f'<div class="stat"><b>{job.clean_reward:.3f}</b><span>mean over clean rollouts</span></div>'
        )
    # failing rollouts first, clean ones last
    order = sorted(job.traces, key=lambda t: (t.outcome == CLEAN, t.index))
    body = "".join(_trace_html(t) for t in order)
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>Trace view: {escape(job.name)}</title><style>{_CSS}</style></head><body><main>"
        f"<h1>{escape(job.name)}</h1>"
        '<p class="sub">Rollouts that did not finish cleanly are open and listed first. '
        "Repeated steps are folded; the first failing step is outlined in red.</p>"
        f'<div class="stats">{"".join(stats)}</div>{body}</main></body></html>'
    )
