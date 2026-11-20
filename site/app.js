(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmt3 = (x) => (x == null ? "n/a" : Number(x).toFixed(3));
  const fmtR = (x) => String(Math.round(Number(x) * 1000) / 1000);
  const mq = window.matchMedia("(max-width:1180px)");

  const OUTCOME = {
    "clean": { label: "Clean", cls: "b-clean", group: "clean" },
    "failed mid-run, graded": { label: "Crashed mid-run", cls: "b-crash", group: "crash" },
    "grade error": { label: "Grader error", cls: "b-graderr", group: "graderr" },
    "cancelled": { label: "Cancelled", cls: "b-other", group: "other" },
    "truncated": { label: "Truncated", cls: "b-other", group: "other" },
  };
  const oc = (o) => OUTCOME[o] || { label: o, cls: "b-other", group: "other" };
  const badge = (o) => `<span class="badge ${oc(o).cls}">${esc(oc(o).label)}</span>`;

  let D, runs, state = { run: 0, sel: null, filter: "all", fold: true, open: new Set() };

  fetch("data.json").then((r) => r.json()).then((data) => {
    D = data;
    // rollouts that did not finish cleanly first, like the CLI
    runs = [...D.traces].sort((a, b) => (a.outcome === "clean") - (b.outcome === "clean") || a.index - b.index);
    const startRun = runs.find((t) => t.outcome !== "clean") || runs[0];
    state.run = startRun.index;
    state.sel = startRun.first_failure ? startRun.first_failure.step : 1;
    renderSummary();
    renderFilters();
    renderRuns();
    renderRun();
    renderDrawer();
  });

  /* ---------- job summary ---------- */
  function renderSummary() {
    const j = D.job;
    $("job-name").textContent = j.name;
    $("src-file").textContent = D.source_file;
    $("synth-tag").title = D.synthetic_note;
    $("synth-note").innerHTML = `<b>Synthetic example.</b> ${esc(D.synthetic_note.replace(/^Synthetic data: /, ""))} Numbers come from running hudtrace on that recorded job.`;
    let h = `HUD reports reward <b>${fmt3(j.reward)}</b> for this job`;
    if (j.n_failed_mid_run) {
      h += `, but <span class="hl-bad">${j.n_failed_mid_run} of the ${j.n_in_mean} rollouts in that mean crashed mid-run</span>`;
      h += ` and still add ${Number(j.failed_mid_run_reward).toFixed(1)} reward between them.`;
    } else h += ".";
    $("headline").innerHTML = h;
    const stats = [
      ["accent", fmt3(j.reward), "Reported reward (job.reward, mean of graded rollouts)"],
      ["", j.n_rollouts, "Rollouts in this job"],
      [j.n_failed_mid_run ? "warn" : "", j.n_failed_mid_run, "Crashed mid-run but still counted in the reward"],
      [j.n_grade_errors ? "bad" : "", j.n_grade_errors, "Grader errors, left out of the reward"],
      ["", fmt3(j.clean_reward), "Reward over clean rollouts only"],
    ];
    $("stats").innerHTML = stats.map(([c, v, l]) => `<div class="stat ${c}"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  }

  /* ---------- runs list ---------- */
  function renderFilters() {
    const n = (g) => runs.filter((t) => oc(t.outcome).group === g).length;
    const fs = [["all", "All", runs.length], ["crash", "Crashed", n("crash")], ["graderr", "Grader error", n("graderr")], ["clean", "Clean", n("clean")]].filter((f) => f[0] === "all" || f[2]);
    $("filters").innerHTML = fs.map(([k, l, c]) => `<button class="filter" role="tab" data-f="${k}" aria-selected="${state.filter === k}">${esc(l)} ${c}</button>`).join("");
    $("filters").onclick = (e) => {
      const b = e.target.closest(".filter"); if (!b) return;
      state.filter = b.dataset.f; renderFilters(); renderRuns();
    };
  }

  function renderRuns() {
    const shown = runs.filter((t) => state.filter === "all" || oc(t.outcome).group === state.filter);
    $("runs-count").textContent = `${shown.length} of ${runs.length} rollouts`;
    $("run-list").innerHTML = shown.map((t) => {
      const ff = t.first_failure ? ` · <span class="ff">first fail: step ${t.first_failure.step}</span>` : "";
      return `<li><button class="run" data-i="${t.index}" aria-current="${t.index === state.run}">
        <div class="run-top"><span class="run-slug">${esc(t.slug)}</span>${badge(t.outcome)}</div>
        <div class="run-meta">reward ${fmtR(t.reward)} · ${t.n_steps} steps${ff}</div></button></li>`;
    }).join("");
    $("run-list").onclick = (e) => {
      const b = e.target.closest(".run"); if (!b) return;
      const t = D.traces[+b.dataset.i];
      state.run = t.index; state.open.clear();
      state.sel = t.first_failure ? t.first_failure.step : 1;
      renderRuns(); renderRun(); renderDrawer();
      if (window.matchMedia("(max-width:720px)").matches) document.querySelector(".timeline").scrollIntoView({ behavior: "smooth" });
    };
  }

  /* ---------- timeline ---------- */
  const cur = () => D.traces[state.run];
  const lastErrorStep = (t) => { for (let i = t.steps.length - 1; i >= 0; i--) if (t.steps[i].error) return t.steps[i].step_id || i + 1; return null; };

  function renderRun() {
    const t = cur();
    $("run-head").innerHTML = `<div class="run-title"><h2>${esc(t.slug)}</h2>${badge(t.outcome)}</div>
      <div class="kv"><span>Reward <b>${fmtR(t.reward)}</b></span>
      <span>Counted in job reward <b>${t.counts_in_mean ? "yes" : "no"}</b></span>
      <span>Steps <b>${t.n_steps}</b></span><span>Rows after folding <b>${t.n_rows}</b></span>
      <span>Status <b>${esc(t.status)}</b></span>${t.answer ? `<span>Final answer <b>${esc(t.answer)}</b></span>` : ""}</div>`;

    const ff = t.first_failure;
    let banner = "";
    if (ff) {
      const les = lastErrorStep(t);
      const ended = t.last_error && t.status === "error" && t.last_error !== ff.failure
        ? `<div class="end">Rollout ended at step ${les}: <code>${esc(t.last_error)}</code></div>` : "";
      const recovered = t.outcome === "clean" ? `<div class="end">The agent recovered and the rollout finished clean.</div>` : "";
      banner = `<div class="banner"><div><div class="t">First failing step: ${ff.step} of ${t.n_steps}</div>
        <div class="m">${esc(ff.title)}: ${esc(ff.failure)}</div>${ended}${recovered}</div>
        <button class="jump" id="jump">Jump to step ${ff.step}</button></div>`;
    } else {
      banner = `<div class="banner ok"><div><div class="t">No failing step</div><div class="end">Every step ran without an error and the rollout finished clean.</div></div></div>`;
    }
    $("fail-banner").innerHTML = banner;
    if (ff) $("jump").onclick = () => selectStep(ff.step, true);
    $("fold-toggle").checked = state.fold;
    $("fold-toggle").onchange = (e) => { state.fold = e.target.checked; renderSteps(); };
    renderSteps();
  }

  function stepLi(r, t, extraCls = "") {
    const ffs = t.first_failure && t.first_failure.step;
    const isFirst = ffs != null && r.first <= ffs && ffs <= r.last && r.failed;
    const sel = state.sel != null && r.first <= state.sel && state.sel <= r.last;
    const cls = ["step", extraCls, r.failed ? "failed" : "", isFirst ? "first" : "", sel ? "sel" : ""].join(" ");
    const flag = isFirst ? `<span class="flag">First failure</span>` : "";
    const times = r.count > 1 ? `<span class="times" title="${r.count} identical steps folded into this row">×${r.count}</span>` : "";
    const why = r.failed && r.failure && r.failure !== r.detail ? `<div class="why">${esc(r.failure)}</div>` : "";
    return `<li class="${cls}" data-s="${r.first}" tabindex="0">
      <span class="num">${esc(r.span)}</span><span class="src ${esc(r.source)}">${esc(r.source)}</span>
      <div class="body"><div class="title">${flag}${esc(r.title)}</div>${r.detail ? `<div class="detail">${esc(r.detail)}</div>` : ""}${why}</div>
      <span class="right">${times}</span></li>`;
  }

  function renderSteps() {
    const t = cur();
    const folded = state.fold;
    $("tl-count").textContent = folded
      ? `${t.n_steps} steps shown as ${t.n_rows} rows`
      : `${t.n_steps} steps, unfolded`;
    let html = "";
    if (!folded) {
      html = t.raw_rows.map((r) => stepLi(r, t)).join("");
    } else {
      for (const it of t.items) {
        if (it.kind !== "loop") { html += stepLi(it, t); continue; }
        const ffs = t.first_failure && t.first_failure.step;
        const hasFirst = ffs != null && it.first <= ffs && ffs <= it.last;
        const open = state.open.has(it.first);
        const chain = it.rows.map((r) => esc(r.title) + (r.failed ? " (error)" : "")).join(" → ");
        const inner = t.raw_rows.filter((r) => r.first >= it.first && r.last <= it.last).map((r) => stepLi(r, t)).join("");
        html += `<li class="loop ${open ? "open" : ""}" data-loop="${it.first}">
          <button class="loop-head ${hasFirst ? "first" : ""}" aria-expanded="${open}">
            <span class="num">${it.first}-${it.last}</span>
            <span class="lbl"><span class="chev">▸</span>Repeated loop: ${it.rows.length} steps, ${it.reps} times${hasFirst ? ` <span class="flag" style="margin-left:6px">First failure inside (step ${ffs})</span>` : ""}
              <span class="sub">${chain}</span></span>
            <span class="times" title="${it.reps} repeats folded into this row">×${it.reps}</span>
          </button>
          ${open ? `<ol class="steps loop-body">${inner}</ol>` : ""}</li>`;
      }
    }
    $("steps").innerHTML = html;
    $("steps").onclick = (e) => {
      const lh = e.target.closest(".loop-head");
      if (lh) {
        const k = +lh.parentElement.dataset.loop;
        state.open.has(k) ? state.open.delete(k) : state.open.add(k);
        renderSteps(); return;
      }
      const s = e.target.closest(".step"); if (s) selectStep(+s.dataset.s, false, true);
    };
    $("steps").onkeydown = (e) => { if (e.key === "Enter") { const s = e.target.closest(".step"); if (s) selectStep(+s.dataset.s, false, true); } };
  }

  function selectStep(n, scroll, openDrawer) {
    const t = cur();
    state.sel = n;
    const loop = t.items.find((it) => it.kind === "loop" && it.first <= n && n <= it.last);
    if (loop && state.fold) state.open.add(loop.first);
    renderSteps(); renderDrawer();
    if (scroll) {
      const el = document.querySelector(`.step[data-s="${n}"]`);
      if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    if ((openDrawer || scroll) && mq.matches) showDrawer(true);
  }

  /* ---------- details drawer ---------- */
  function showDrawer(on) {
    $("drawer").classList.toggle("open", on);
    $("scrim").classList.toggle("open", on);
  }
  $("drawer-close").onclick = () => showDrawer(false);
  $("scrim").onclick = () => showDrawer(false);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") showDrawer(false); });

  function renderDrawer() {
    const t = cur();
    const n = state.sel;
    const raw = t.steps.find((s) => s.step_id === n) || t.steps[n - 1];
    const row = t.raw_rows.find((r) => r.first === n);
    if (!raw || !row) { $("drawer-body").innerHTML = `<p class="d-empty">Click any step in the timeline to see its details here.</p>`; return; }
    const isFirst = t.first_failure && t.first_failure.step === n;
    const foldedIn = t.items.find((it) => it.first <= n && n <= it.last && (it.kind === "loop" || it.count > 1));
    const foldTxt = foldedIn ? (foldedIn.kind === "loop" ? `loop of steps ${foldedIn.first}-${foldedIn.last}, ×${foldedIn.reps}` : `row ${foldedIn.span}, ×${foldedIn.count}`) : "not folded";
    $("drawer-body").innerHTML = `
      <div class="d-nav"><button id="d-prev" ${n <= 1 ? "disabled" : ""}>← Prev step</button><button id="d-next" ${n >= t.n_steps ? "disabled" : ""}>Next step →</button></div>
      <div class="d-title">${esc(row.title)}</div>
      ${row.failed ? `<div class="d-fail"><b>${isFirst ? "First failing step" : "Failed step"}.</b> ${esc(row.failure)}</div>` : ""}
      <dl class="d-grid">
        <dt>Step</dt><dd>${n} of ${t.n_steps}</dd>
        <dt>Source</dt><dd>${esc(row.source)}</dd>
        <dt>Result</dt><dd>${row.failed ? "error" : "ok"}</dd>
        <dt>Folding</dt><dd>${esc(foldTxt)}</dd>
        <dt>Rollout</dt><dd>${esc(t.slug)}</dd>
      </dl>
      <div class="d-sec">Raw step (Trace.steps[${n - 1}], nulls dropped)</div>
      <pre class="json">${esc(JSON.stringify(raw, null, 2))}</pre>
      <div class="d-sec">Rollout grade</div>
      <pre class="json">${esc(JSON.stringify(t.grade, null, 2))}</pre>`;
    $("d-prev").onclick = () => selectStep(n - 1, true);
    $("d-next").onclick = () => selectStep(n + 1, true);
  }
})();
