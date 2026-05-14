"""Tests for OpenAI backed code generation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest

from aivenv.execution.code_generator import CodeGenerator, CodeGenError, SYSTEM_PROMPT_PATHET


@dataclass
class _Message:
    content: Any


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]


class _FakeCompletions:
    def __init__(self, *, response: Any | None = None, error: BaseException | None = None, delay: float = 0) -> None:
        self.response = response
        self.error = error
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.response


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = _FakeChat(completions)


def _generator(completions: _FakeCompletions, *, timeout_seconds: float = 60) -> CodeGenerator:
    return CodeGenerator(client=_FakeClient(completions), model="gpt-test", timeout_seconds=timeout_seconds)


@pytest.mark.asyncio
async def test_generate_calls_openai_with_python_system_prompt_and_returns_code() -> None:
    completions = _FakeCompletions(response=_Response([_Choice(message=_Message(content='print("hello")'))]))
    generator = _generator(completions)

    code = await generator.generate("print a greeting")

    assert code == 'print("hello")\n'
    assert completions.calls[0]["model"] == "gpt-test"
    assert completions.calls[0]["messages"] == [
        {"role": "system", "content": SYSTEM_PROMPT_PATHET},
        {"role": "user", "content": "print a greeting"},
    ]
    assert "self-contained Python" in SYSTEM_PROMPT_PATHET


@pytest.mark.asyncio
async def test_generate_strips_python_markdown_fence() -> None:
    response = _Response([_Choice(message=_Message(content='```python\nprint("ok")\n```'))])
    generator = _generator(_FakeCompletions(response=response))

    assert await generator.generate("make script") == 'print("ok")\n'


@pytest.mark.asyncio
async def test_generate_strips_unlabeled_markdown_fence() -> None:
    response = _Response([_Choice(message=_Message(content='```\nprint("ok")\n```'))])
    generator = _generator(_FakeCompletions(response=response))

    assert await generator.generate("make script") == 'print("ok")\n'


@pytest.mark.asyncio
async def test_generate_enforces_asyncio_timeout() -> None:
    generator = _generator(_FakeCompletions(response=_Response(choices=[]), delay=0.05), timeout_seconds=0.01)

    with pytest.raises(CodeGenError, match="timed out after 0.01 seconds"):
        await generator.generate("slow")


@pytest.mark.asyncio
async def test_generate_sanitizes_api_key_from_openai_errors() -> None:
    secret = "sk-test-secret-token-1234567890"
    generator = _generator(_FakeCompletions(error=RuntimeError(f"request failed for {secret}")))

    with pytest.raises(CodeGenError) as exc_info:
        await generator.generate("do something")

    message = str(exc_info.value)
    assert secret not in message
    assert "[REDACTED]" in message


@pytest.mark.asyncio
async def test_generate_rejects_invalid_response() -> None:
    generator = _generator(_FakeCompletions(response=_Response(choices=[])))

    with pytest.raises(CodeGenError, match="invalid response"):
        await generator.generate("make script")


@pytest.mark.asyncio
async def test_generate_rejects_empty_instruction() -> None:
    generator = _generator(_FakeCompletions(response=_Response(choices=[])))

    with pytest.raises(CodeGenError, match="Instruction must not be empty"):
        await generator.generate("   ")
