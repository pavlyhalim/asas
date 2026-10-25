"""A guarded model: the host's inspection around every model call of a run.

A host that screens what goes to a model (prompt injection in the data a call
carries) and what comes back (unsafe content) keeps that screening when its
runs move onto the SDK by handing `run_agent` a :class:`GuardedModel` as its
`run_model`. The package holds no rules: the host's two inspectors decide, and
an inspector that raises refuses the call. Its exception leaves the run as it
is, so a host's own refusal type reaches the host's handler.

    model = GuardedModel(
        provider.get_model("gpt-5"),
        inspect_prompt=my_prompt_check,      # (texts, system) -> None or raise
        inspect_response=my_response_check,  # (text, system) -> None or raise
    )
    await run_agent(snapshot, dispatch, ask, renderer=r, run_model=model)

The prompt inspector sees every text the call sends that is not the system
instructions: the messages and the tool results, which are where data a
person or a document controls arrives. The response inspector sees the
answer's text and the arguments of every tool call it makes.

Imports the Agents SDK, so ``import asas_agent`` loads this module only when
its name is first used.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from agents import Model

from .seams import SkillAware

#: (the texts the call sends, the system instructions) -> None, or raise to refuse.
PromptInspector = Callable[[list[str], str | None], Awaitable[None]]
#: (the answer's text, the system instructions) -> None, or raise to refuse.
ResponseInspector = Callable[[str, str | None], Awaitable[None]]


def _content_texts(content: Any) -> Iterable[str]:
    if isinstance(content, str):
        yield content
        return
    for part in content or []:
        text = (
            part.get("text") if isinstance(part, dict) else getattr(part, "text", None)
        )
        if isinstance(text, str):
            yield text


def input_texts(input: Any) -> list[str]:
    """The texts of a call's input items: message content and tool outputs."""
    if isinstance(input, str):
        return [input]
    texts: list[str] = []
    for item in input:
        if not isinstance(item, dict):
            continue
        if "content" in item:
            texts.extend(_content_texts(item["content"]))
        output = item.get("output")
        if isinstance(output, str):
            texts.append(output)
        else:
            texts.extend(_content_texts(output))
    return [t for t in texts if t]


def response_text(response: Any) -> str:
    """The answer's text and every tool call's arguments, one per line."""
    texts: list[str] = []
    for item in getattr(response, "output", None) or []:
        texts.extend(_content_texts(getattr(item, "content", None)))
        arguments = getattr(item, "arguments", None)
        if isinstance(arguments, str):
            texts.append(arguments)
    return "\n".join(t for t in texts if t)


class GuardedModel(Model):
    """`inner` with the host's prompt inspection before every call and its
    response inspection before the answer is used."""

    def __init__(
        self,
        inner: Model,
        *,
        inspect_prompt: PromptInspector,
        inspect_response: ResponseInspector,
    ):
        self.inner = inner
        self.inspect_prompt = inspect_prompt
        self.inspect_response = inspect_response

    async def get_response(self, system_instructions, input, *args, **kwargs):
        await self.inspect_prompt(input_texts(input), system_instructions)
        response = await self.inner.get_response(
            system_instructions, input, *args, **kwargs
        )
        await self.inspect_response(response_text(response), system_instructions)
        return response

    def bind(self, active_skill) -> None:
        # A model by reference behind the guard still learns the active skill.
        if isinstance(self.inner, SkillAware):
            self.inner.bind(active_skill)

    def get_retry_advice(self, request):
        return self.inner.get_retry_advice(request)

    def stream_response(self, *args, **kwargs):
        # A streamed answer reaches the run before it can be inspected whole.
        raise NotImplementedError(
            "GuardedModel does not stream: an answer is inspected before it is used"
        )

    async def close(self) -> None:
        await self.inner.close()


__all__ = [
    "GuardedModel",
    "PromptInspector",
    "ResponseInspector",
    "input_texts",
    "response_text",
]
