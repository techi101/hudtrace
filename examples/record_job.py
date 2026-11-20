"""Record a real HUD job with no model calls, then dump its traces to JSON.

Runs hud-python's own ``Taskset.run`` with ``LocalRuntime`` and a scripted agent that
records ``AgentStep`` / ``ToolStep`` objects the way a tool agent would. Nothing is sent
anywhere: without ``HUD_API_KEY`` hud's platform reporting is a no-op.

The agent is scripted (synthetic behaviour); the trace format, grading and status
handling are the SDK's own.

    python examples/record_job.py examples/job_traces.json
"""

from __future__ import annotations

import asyncio
import json
import sys

from hud import Environment, Run, Task, Taskset
from hud.agents.base import Agent
from hud.agents.types import AgentConfig, AgentStep, ToolStep
from hud.runtime import LocalRuntime
from hud.types import TextContent, ToolCall, ToolResult

env = Environment("debug-logs")


@env.template()
async def find_error(behaviour: str):
    answer = yield f"[{behaviour}] Find the line in app.log that explains the crash; answer 'yes' when found."
    yield 1.0 if answer == "yes" else 0.0


@env.template()
async def broken_grader(behaviour: str):
    yield f"[{behaviour}] Same task, but this task's grader is broken."
    raise RuntimeError("grader could not open /srv/expected.json")
    yield 0.0


def tool(run: Run, name: str, args: dict, text: str, *, error: bool = False) -> None:
    call = ToolCall(name=name, arguments=args)
    run.record(AgentStep(content=None, tool_calls=[call]))
    result = ToolResult(content=[TextContent(type="text", text=text)], isError=error, call_id=call.id)
    run.record(ToolStep(call=call, result=result))


def answer(run: Run, text: str) -> None:
    run.record(AgentStep(content=text, done=True))
    run.trace.content = text


class ScriptedAgent(Agent):
    """Plays one fixed behaviour per task, picked from the prompt tag."""

    async def __call__(self, run: Run) -> None:
        tag = run.prompt_text.split("]")[0].strip("[")
        if tag == "clean":
            tool(run, "bash", {"cmd": "grep -n ERROR app.log"}, "212: ERROR db pool exhausted")
            answer(run, "yes")
        elif tag == "recovers":
            tool(run, "bash", {"cmd": "cat logs/app.log"}, "cat: logs/app.log: No such file", error=True)
            tool(run, "bash", {"cmd": "grep -n ERROR app.log"}, "212: ERROR db pool exhausted")
            answer(run, "yes")
        elif tag == "loops-then-crashes":
            tool(run, "bash", {"cmd": "ls"}, "app.log  README.md")
            for _ in range(6):  # the agent keeps retrying the same failing call
                tool(run, "bash", {"cmd": "tail -n 50 app.log.1"}, "tail: cannot open 'app.log.1'", error=True)
            answer(run, "yes")
            raise RuntimeError("gateway 403: quota exceeded")  # crash after the work is done
        elif tag == "crashes-early":
            tool(run, "bash", {"cmd": "cat app.log"}, "x" * 200)
            raise RuntimeError("context length exceeded")
        elif tag == "grader-broken":
            tool(run, "bash", {"cmd": "grep -n ERROR app.log"}, "212: ERROR db pool exhausted")
            answer(run, "yes")


async def main(out: str) -> None:
    rows = [
        Task(env="debug-logs", id="find_error", slug="clean", args={"behaviour": "clean"}),
        Task(env="debug-logs", id="find_error", slug="recovers", args={"behaviour": "recovers"}),
        Task(
            env="debug-logs",
            id="find_error",
            slug="loops-then-crashes",
            args={"behaviour": "loops-then-crashes"},
        ),
        Task(env="debug-logs", id="find_error", slug="crashes-early", args={"behaviour": "crashes-early"}),
        Task(env="debug-logs", id="broken_grader", slug="grader-broken", args={"behaviour": "grader-broken"}),
    ]
    job = await Taskset("debug-logs", rows).run(ScriptedAgent(AgentConfig()), runtime=LocalRuntime(env))
    print(f"Job.reward={job.reward:.3f} len(Job.errors)={len(job.errors)}")
    failed = getattr(job, "failed_mid_run", None)
    print("Job.failed_mid_run:", "not on this hud version" if failed is None else len(failed))
    payload = {"name": "debug-logs (scripted agent)", "traces": [t.model_dump(mode="json") for t in job.traces]}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, default=str)
    print(f"wrote {out}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "job_traces.json"))
