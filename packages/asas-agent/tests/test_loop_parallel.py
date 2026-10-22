"""Several tool calls in one model answer: the read-only ones run together, any other
waits for the calls before it and holds back the calls after it, and the trace and
the results the model reads keep the order the model issued them in."""

import asyncio
import json
import time

from agents import Model
from agents.items import ModelResponse
from agents.usage import Usage
from conftest import run
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from test_loop import RENDERER, never_asked, snapshot

from asas_agent import run_agent


class AnswerModel(Model):
    """Each step of the script is one model answer: a list of (tool, arguments)
    calls, or the closing words."""

    def __init__(self, script):
        self.script = iter(script)
        self.inputs = []

    async def get_response(self, system_instructions, input, *a, **k):
        self.inputs.append(input)
        step = next(self.script)
        if isinstance(step, str):
            output = [
                ResponseOutputMessage(
                    id="message",
                    role="assistant",
                    type="message",
                    status="completed",
                    content=[
                        ResponseOutputText(
                            text=step, annotations=[], type="output_text"
                        )
                    ],
                )
            ]
        else:
            output = [
                ResponseFunctionToolCall(
                    id=f"fc-{i}",
                    call_id=f"call-{i}",
                    name=name,
                    arguments=json.dumps(args),
                    type="function_call",
                )
                for i, (name, args) in enumerate(step, start=1)
            ]
        return ModelResponse(output=output, usage=Usage(), response_id=None)

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


def read_only_snapshot():
    snap = snapshot()
    snap["active_skill"] = "triage"
    for d in snap["tools"]:
        if d["name"] == "ticket_read":
            d["read_only"] = True
    return snap


def slow_dispatch(log, delays):
    async def dispatch(call_id, name, args, active):
        log.append(("start", call_id))
        await asyncio.sleep(delays.get(call_id, 0))
        log.append(("end", call_id))
        return {"ok": True, "data": {"revision": int(call_id[-1]), "for": call_id}}

    return dispatch


def outputs(model_input):
    return [
        (item["call_id"], json.loads(item["output"])["data"]["for"])
        for item in model_input
        if isinstance(item, dict) and item.get("type") == "function_call_output"
    ]


def test_two_slow_reads_in_one_answer_take_the_time_of_one_and_keep_call_order():
    model = AnswerModel(
        [[("ticket_read", {"part": "a"}), ("ticket_read", {"part": "b"})], "Done."]
    )
    log = []
    started = time.monotonic()
    result = run(
        run_agent(
            read_only_snapshot(),
            slow_dispatch(log, {"call-1": 0.3, "call-2": 0.2}),
            never_asked,
            renderer=RENDERER,
            model=model,
        )
    )
    elapsed = time.monotonic() - started
    assert elapsed < 0.45, elapsed
    # The second finished first; the trace and the model's input keep the call order.
    assert log == [
        ("start", "call-1"),
        ("start", "call-2"),
        ("end", "call-2"),
        ("end", "call-1"),
    ]
    assert [(t["index"], t["call_id"]) for t in result["tool_trace"]] == [
        (1, "call-1"),
        (2, "call-2"),
    ]
    assert outputs(model.inputs[1]) == [("call-1", "call-1"), ("call-2", "call-2")]


def test_a_write_waits_for_the_reads_before_it_and_holds_back_the_reads_after_it():
    model = AnswerModel(
        [
            [
                ("ticket_read", {}),
                ("ticket_update", {"late": True}),
                ("ticket_read", {}),
            ],
            "Done.",
        ]
    )
    log = []
    result = run(
        run_agent(
            read_only_snapshot(),
            slow_dispatch(log, {"call-1": 0.1, "call-2": 0.1}),
            never_asked,
            renderer=RENDERER,
            model=model,
        )
    )
    assert log == [
        ("start", "call-1"),
        ("end", "call-1"),
        ("start", "call-2"),
        ("end", "call-2"),
        ("start", "call-3"),
        ("end", "call-3"),
    ]
    assert [t["call_id"] for t in result["tool_trace"]] == [
        "call-1",
        "call-2",
        "call-3",
    ]
    assert [i for i, _ in outputs(model.inputs[1])] == ["call-1", "call-2", "call-3"]


def test_a_tool_not_declared_read_only_runs_alone():
    model = AnswerModel([[("ticket_read", {}), ("ticket_read", {})], "Done."])
    snap = snapshot()
    log = []
    result = run(
        run_agent(
            snap,
            slow_dispatch(log, {"call-1": 0.1}),
            never_asked,
            renderer=RENDERER,
            model=model,
        )
    )
    assert log == [
        ("start", "call-1"),
        ("end", "call-1"),
        ("start", "call-2"),
        ("end", "call-2"),
    ]
    assert [t["call_id"] for t in result["tool_trace"]] == ["call-1", "call-2"]
