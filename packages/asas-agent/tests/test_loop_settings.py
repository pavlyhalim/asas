"""The release's settings reach the run: its model settings lay over the loop's, and
tracing is on only when the release says so, named after it and carrying its id."""

from agents import set_trace_processors
from agents.tracing import TracingProcessor
from conftest import run
from test_loop import RENDERER, ScriptedModel, never_asked, snapshot

from asas_agent import model_settings, run_agent


class Collect(TracingProcessor):
    def __init__(self):
        self.traces = []

    def on_trace_start(self, trace):
        self.traces.append(trace.export())

    def on_trace_end(self, trace):
        pass

    def on_span_start(self, span):
        pass

    def on_span_end(self, span):
        pass

    def shutdown(self):
        pass

    def force_flush(self):
        pass


def with_settings(settings):
    shot = snapshot()
    shot["release"] = {**shot["release"], "id": "r-1", "settings": settings}
    return shot


async def no_tools(*args):
    raise AssertionError("no tool was expected")


def test_the_releases_model_settings_lay_over_the_loops():
    shot = with_settings(
        {"model": {"temperature": 0.2, "reasoning": {"effort": "low"}}}
    )
    settings = model_settings(None, shot["release"])
    assert settings.temperature == 0.2 and settings.reasoning.effort == "low"
    assert settings.parallel_tool_calls is True and settings.store is False
    assert model_settings(None, snapshot()["release"]) == model_settings()


def test_tracing_follows_the_release():
    collect = Collect()
    set_trace_processors([collect])
    try:
        run(
            run_agent(
                snapshot(),
                no_tools,
                never_asked,
                renderer=RENDERER,
                model=ScriptedModel([(None, "Off.")]),
            )
        )
        assert collect.traces == []
        run(
            run_agent(
                with_settings({"tracing": {"enabled": True}}),
                no_tools,
                never_asked,
                renderer=RENDERER,
                model=ScriptedModel([(None, "On.")]),
                group_id="session-1",
                trace_metadata={"tenant": "t-1"},
            )
        )
    finally:
        set_trace_processors([])
    [trace] = collect.traces
    assert trace["workflow_name"] == "Support"
    assert trace["group_id"] == "session-1"
    assert trace["metadata"] == {"tenant": "t-1", "release_id": "r-1"}
