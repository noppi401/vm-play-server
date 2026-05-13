from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from aivenv.config import Settings, load_settings


def clear_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "OPENAI_API_KEY",
        "AIVENV_OPENAI_API_KEY",
        "NGROK_AUTHTOKEN",
        "AIVENV_NGROK_AUTHTOKEN",
        "AIVENV_HOST",
        "AIVENV_PORT",
        "PORT",
        "AIVENV_LOG_HOST",
        "AIVENV_LOG_PORT",
        "LOG_PORT",
        "AIVENV_OPENAI_MODEL",
        "OPENAI_MODEL",
        "AIVENV_CONTAINER_IMAGE",
        "CONTAINER_IMAGE",
        "AIVENV_CPU_LIMIT",
        "CPU_LIMIT",
        "AIVENV_MEMORY_LIMIT",
        "MEMORY_LIMIT",
        "AIVENV_CLEANUP_ON_EXIT",
        "CLEANUP_ON_EXIT",
        "AIVENV_EXECUTION_TIMEOUT_SECONDS",
        "EXCUTION_TIMEOUT_SECONDS",
        "EXICUTION_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
