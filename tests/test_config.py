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


def test_openai_compatible_server() -> None:
    s = LLMSettings.from_env(
        {
            "FLAKEHUNTER_PROVIDER": "openai-compatible",
            "FLAKEHUNTER_BASE_URL": "http://127.0.0.1:8080/v1",
            "FLAKEHUNTER_API_KEY": "s3cret",
        }
    )
    assert (s.base_url, s.model, s.api_key) == ("http://127.0.0.1:8080/v1", "default", "s3cret")
    assert "s3cret" not in repr(s)


def test_openai_compatible_needs_base_url() -> None:
    with pytest.raises(ConfigError):
        LLMSettings.from_env({}, provider="openai-compatible")


@pytest.mark.parametrize("name", ["openai", "github-models"])
def test_unknown_provider_is_an_error(name: str) -> None:
    with pytest.raises(ConfigError):
        LLMSettings.from_env({"FLAKEHUNTER_PROVIDER": name})


def test_with_model() -> None:
    s = LLMSettings.from_env({})
    assert s.with_model("llama3.1:8b").model == "llama3.1:8b"
    assert s.with_model(None) is s
