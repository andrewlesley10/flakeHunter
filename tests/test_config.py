import pytest

from flakehunter.config import ConfigError, LLMSettings


def test_defaults_to_local_ollama() -> None:
    s = LLMSettings.from_env({})
    assert (s.provider, s.base_url, s.model) == (
        "ollama",
        "http://localhost:11434/v1",
        "llama3.2:3b",
    )


def test_env_overrides() -> None:
    s = LLMSettings.from_env({"FLAKEHUNTER_MODEL": "qwen2.5:7b", "FLAKEHUNTER_TIMEOUT_S": "5"})
    assert (s.model, s.timeout_s) == ("qwen2.5:7b", 5.0)


def test_github_models_uses_github_token() -> None:
    s = LLMSettings.from_env({"FLAKEHUNTER_PROVIDER": "github-models", "GITHUB_TOKEN": "t0k"})
    assert s.base_url == "https://models.github.ai/inference"
    assert s.api_key == "t0k"
    assert "t0k" not in repr(s)


def test_github_models_without_token_is_an_error() -> None:
    with pytest.raises(ConfigError):
        LLMSettings.from_env({}, provider="github-models")


def test_unknown_provider_is_an_error() -> None:
    with pytest.raises(ConfigError):
        LLMSettings.from_env({"FLAKEHUNTER_PROVIDER": "openai"})


def test_with_model() -> None:
    s = LLMSettings.from_env({})
    assert s.with_model("llama3.1:8b").model == "llama3.1:8b"
    assert s.with_model(None) is s
