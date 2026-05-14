"""OpenAI backed code generation."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Protocol, cast

from openai import AsyncOpenAI

try:
    from aivenv.execution.errors import CodeGenError
except ModuleNotFoundError:

    class CodeGenError(Exception):
        """Raised when AI code generation fails."""


DEFAULT_MODEL = "gpt-4o"
DEFAULT_TIMEOUT_SECONDS = 60.0
SYSTEM_PROMPT_PATHET = """You are generating code for an isolated execution environment.
Return exactly one complete, self-contained Python 3.11 script.
Do not return Markdown fences, explanations, filenames, shell commands, or multiple files.
The script must be executable as-is with python script.py.
Handle expected runtime errors gracefully and print useful status or result information.
Never include secrets, credentials, or host-specific paths.
"""

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,]+"),
)
_FENCE_RE = re.compile(r"^```([A-Za-z0-9_+.-]+)?\s*\n(.*?)\n```$", re.DOTALL)


class _Completions(Protocol):
    async def create(self, **kwargs: Any) -> Any:
        ...


class _Chat(Protocol):
    completions: _Completions


class _Client(Protocol):
    chat: _Chat


class CodeGenerator:
    """Generate a single self-contained Python script via AsyncOpenAI."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: _Client | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        if not model.strip():
            raise CodeGenError("OpenAI model must not be empty.")
        if timeout_seconds <= 0:
            raise CodeGenError("OpenAI generation timeout must be greater than zero.")
        if client is None and not (api_key and api_key.strip()):
            raise CodeGenError("OpenAI API key is required for code generation.")

        self._model = model.strip()
        self._timeout_seconds = float(timeout_seconds)
        self._logger = logger or logging.getLogger(__name__)
        self._client: _Client = client or cast(_Client, AsyncOpenAI(api_key=api_key))

    async def generate(self, instruction: str) -> str:
        """Generate executable Python source code from a natural-language instruction."""
        normalized = instruction.strip()
        if not normalized:
            raise CodeGenError("Instruction must not be empty.")

        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT_PATHET},
                        {"role": "user", "content": normalized},
                    ],
                    temperature=0.2,
                ),
                timeout=self._timeout_seconds,
            )
            return self._extract_code(response)
        except asyncio.TimeoutError as exc:
            message = f"OpenAI code generation timed out after {self._timeout_seconds:g} seconds."
            self._logger.error(message)
            raise CodeGenError(message) from exc
        except CodeGenError:
            raise
        except Exception as exc:  # noqa: BLE001
            message = f"OpenAI code generation failed: {self.sanitize_message(str(exc) or exc.__class__.__name__)}"
            self._logger.error(message)
            raise CodeGenError(message) from exc

    def _extract_code(self, response: Any) -> str:
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            message = f"OpenAI returned an invalid response: {self.sanitize_message(str(exc) or exc.__class__.__name__)}"
            self._logger.error(message)
            raise CodeGenError(message) from exc

        if not isinstance(content, str):
            message = "OpenAI returned an empty code response."
            self._logger.error(message)
            raise CodeGenError(message)

        code = self._strip_fence(content.strip()).strip()
        if not code:
            message = "OpenAI returned an empty code response."
            self._logger.error(message)
            raise CodeGenError(message)
        return code + "\n"

    @staticmethod
    def _strip_fence(content: str) -> str:
        match = _FENCE_RE.fullmatch(content.strip())
        if not match:
            return content

        language = (match.group(1) or "").lower()
        if language in {"", "python", "py", "python3"}:
            return match.group(2)
        return content

    @staticmethod
    def sanitize_message(message: str) -> str:
        """Redact API keys and auth tokens from a public error message."""
        sanitized = message
        for pattern in SECRET_PATTERNS:
            sanitized = pattern.sub(
                lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]",
                sanitized,
            )
        return sanitized


__all__ = ["CodeGenerator", "CodeGenError", "SYSTEM_PROMPT_PATHET"]
