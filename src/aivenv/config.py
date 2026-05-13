"""Application configuration for the AI virtual execution environment."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict



class Settings(BaseSettings):
    """Runtime settings loaded from environment variables and CLI overrides."""

    model_config = SettingsConfigDict(
        env_prefix="AIVENV_",
        case_sensitive=False,
        extra="ignore",
    )

    openai_api_key: SecretStr = Field(
        validation_alias=AliasChoices("AIVENV_OPENAI_API_KEY", "OPENAI_API_KEY")
    )
    ngrok_authtoken: SecretStr = Field(
        validation_alias=AliasChoices("AIVENV_NGROK_AUTHTOKEN", "NGROK_AUTHTOKEN")
    )
    host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("AIVENV_HOST"))
    port: int = Field(default=8080, validation_alias=AliasChoices("AIVENV_PORT", "PORT"))
    log_host: str = Field(default="127.0.0.1", validation_alias=AliasChoices("AIVENV_LOG_HOST"))
    log_port: int = Field(default=8081, validation_alias=AliasChoices("AIVENV_LOG_PORT", "LOG_PORT"))
    openai_model: str = Field(
        default="gpt-4o",
        validation_alias=AliasChoices("AIVENV_OPENAI_MODEL", "OPENAI_MODEL"),
    )
    container_image: str = Field(
        default="python:3.11-slim",
        validation_alias=AliasChoices("AIVENV_CONTAINER_IMAGE", "CONTAINER_IMAGE"),
    )
    cpu_limit: float = Field(default=1.0, validation_alias=AliasChoices("AIVENV_CPU_LIMIT", "CPU_LIMIT"))
    memory_limit: str = Field(default="512m", validation_alias=AliasChoices("AIVENV_MEMORY_LIMIT", "MEMORY_LIMIT"))
    cleanup_on_exit: bool = Field(
        default=True,
        validation_alias=AliasChoices("AIVENV_CLEANUP_ON_EXIT", "CLEANUP_ON_EXIT"),
    )
    execution_timeout_seconds: int = Field(
        default=600,
        validation_alias=AliasChoices(
            "AIVENV_EXECUTION_TIMEOUT_SECONDS",
            "EXECUTION_TIMEOUT_SECONDS",
            "EXICUTION_TIMEOUT_SECONDS",
        ),
    )

    @field_validator("host", "log_host", "openai_model", "container_image", "memory_limit")
    @classmethod
    def _non_empty_string(cls, v: str) -> str:
        if not v:
            raise ValueError("must not be empty")
        return v

    @field_validator("port", "log_port")
    @classmethod
    def _valid_port(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("must be between 1 and 65535")
        return v

    @field_validator("cpu_limit")
    @classmethod
    def _positive_cpu_limit(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("must be greater than 0")
        return v

    @field_validator("execution_timeout_seconds")
    @classmethod
    def _positive_timeout(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be greater than 0")
        return v

    @property
    def openai_api_key_value(self) -> str:
        return self.openai_api_key.get_secret_value()

    @property
    def ngrok_authtoken_value(self) -> str:
        return self.ngrok_authtoken.get_secret_value()

    @property
    def log_server_url(self) -> str:
        return f"http://{self.log_host}:{self.log_port}"


def load_settings(overrides: Mapping[str, Any] | None = None) -> Settings:
    """Load settings, applying explicit CLI overrides after environment values."""

    return Settings(**(dict(overrides) if overrides else {}))
