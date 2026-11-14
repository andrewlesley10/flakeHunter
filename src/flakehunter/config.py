"""Provider settings, read from the environment.

Both providers are free and speak the OpenAI Chat Completions API, so switching
between them changes only the base URL, the model name and the token:

- ``ollama``: a model running on your own machine (development and evals).
- ``github-models``: GitHub's hosted inference, authenticated with the workflow's
  built-in ``GITHUB_TOKEN`` (needs ``permissions: models: read``).
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast, get_args

Provider = Literal["ollama", "github-models"]
ResponseFormat = Literal["json_schema", "json_object"]

DEFAULTS: dict[Provider, tuple[str, str]] = {
    "ollama": ("http://localhost:11434/v1", "llama3.2:3b"),
    # Model IDs on GitHub Models are "publisher/name". Checked in the catalog
    # (github.com/marketplace?type=models) and verified by the self-test workflow.
    # It is an Action input, so users can change it.
    "github-models": ("https://models.github.ai/inference", "meta/llama-3.3-70b-instruct"),
}


class ConfigError(ValueError):
    """A setting is missing or invalid."""


@dataclass(frozen=True)
class LLMSettings:
    provider: Provider
    base_url: str
    model: str
    api_key: str = "ollama"  # Ollama ignores the key, but the SDK requires one
    timeout_s: float = 120.0
    max_retries: int = 2  # SDK retries with backoff on 429/5xx, honouring Retry-After
    response_format: ResponseFormat = "json_schema"

    def __repr__(self) -> str:  # never print the token
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
        base_url, model = DEFAULTS[chosen]

        if chosen == "github-models":
            api_key = env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or ""
            if not api_key:
                raise ConfigError("github-models needs GITHUB_TOKEN (permissions: models: read)")
        else:
            api_key = "ollama"

        fmt = env.get("FLAKEHUNTER_RESPONSE_FORMAT") or "json_schema"
        if fmt not in get_args(ResponseFormat):
            raise ConfigError(f"unknown response format {fmt!r}")

        return cls(
            provider=chosen,
            base_url=env.get("FLAKEHUNTER_BASE_URL") or base_url,
            model=env.get("FLAKEHUNTER_MODEL") or model,
            api_key=api_key,
            timeout_s=float(env.get("FLAKEHUNTER_TIMEOUT_S") or 120),
            response_format=cast(ResponseFormat, fmt),
        )
