"""python -m hudtrace traces.json [-o report.html]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import load_traces, view_job
from .render import render_html, render_text


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hudtrace", description=__doc__)
    p.add_argument("traces", help="JSON: one Trace, a list of Traces, or {'name', 'traces'}")
    p.add_argument("-o", "--html", help="write a static HTML report here")
    p.add_argument("--quiet", action="store_true", help="skip the terminal view")
    args = p.parse_args(argv)

    name, traces = load_traces(args.traces)
    job = view_job(name, traces)
    if not args.quiet:
        sys.stdout.write(render_text(job))
    if args.html:
        Path(args.html).write_text(render_html(job), encoding="utf-8")
        print(f"wrote {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
