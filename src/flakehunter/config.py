"""Provider settings, read from the environment.

Every provider speaks the OpenAI Chat Completions API, so switching between them
changes only the base URL, the model name and (optionally) a key:

- ``ollama``: a model running on your own machine (development and evals).
- ``openai-compatible``: any other OpenAI-compatible server. Inside GitHub Actions,
  FlakeHunter's Action starts llama.cpp's ``llama-server`` on the runner with the same
  open model, so CI needs no API key either (GitHub Models, the brief's original CI
  provider, was retired on 30 July 2026; see DECISIONS 012).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast, get_args

Provider = Literal["ollama", "openai-compatible"]
ResponseFormat = Literal["json_schema", "json_object"]

OLLAMA_URL = "http://localhost:11434/v1"
OLLAMA_MODEL = "llama3.2:3b"


class ConfigError(ValueError):
    """A setting is missing or invalid."""


@dataclass(frozen=True)
class LLMSettings:
    provider: Provider
    base_url: str
    model: str
    api_key: str = "none"  # local servers ignore the key, but the SDK requires one
    timeout_s: float = 120.0
    max_retries: int = 2  # SDK retries with backoff on 429/5xx, honouring Retry-After
    response_format: ResponseFormat = "json_schema"

    def __repr__(self) -> str:  # never print a key
        return (
            f"LLMSettings(provider={self.provider!r}, base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key='***')"
        )

    def with_model(self, model: str | None) -> "LLMSettings":
        return replace(self, model=model) if model else self

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, provider: str | None = None
    ) -> "LLMSettings":
        """Build settings from ``FLAKEHUNTER_*`` variables, with per-provider defaults."""
        env = os.environ if env is None else env
        name = provider or env.get("FLAKEHUNTER_PROVIDER") or "ollama"
        if name not in get_args(Provider):
            raise ConfigError(f"unknown provider {name!r}; use one of {get_args(Provider)}")
        chosen = cast(Provider, name)

        base_url = env.get("FLAKEHUNTER_BASE_URL") or ""
        model = env.get("FLAKEHUNTER_MODEL") or ""
        if chosen == "ollama":
            base_url, model = base_url or OLLAMA_URL, model or OLLAMA_MODEL
        elif not base_url:
            raise ConfigError("openai-compatible needs FLAKEHUNTER_BASE_URL")

        fmt = env.get("FLAKEHUNTER_RESPONSE_FORMAT") or "json_schema"
        if fmt not in get_args(ResponseFormat):
            raise ConfigError(f"unknown response format {fmt!r}")

        return cls(
            provider=chosen,
            base_url=base_url,
            model=model or "default",
            api_key=env.get("FLAKEHUNTER_API_KEY") or "none",
            timeout_s=float(env.get("FLAKEHUNTER_TIMEOUT_S") or 120),
            response_format=cast(ResponseFormat, fmt),
        )
