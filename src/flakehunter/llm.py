"""LLM classifier: one OpenAI-compatible client for Ollama and GitHub Models.

The model's reply is untrusted input. It is requested as JSON matching ``Verdict``'s
schema, validated by pydantic, and repaired at most once (the validation error is
sent back). Anything that still goes wrong (invalid output, timeouts, connection
errors, rate limits) returns an ``LLMResult`` with ``verdict=None`` and an
``error``. The classifier never raises; ``combine`` decides what to show instead.
"""

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import openai
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject, ResponseFormatJSONSchema
from pydantic import ValidationError

from flakehunter.config import LLMSettings
from flakehunter.models import RuleHint, TestFailure, Verdict
from flakehunter.prompts import SYSTEM_PROMPT, build_user_message


@dataclass(frozen=True)
class LLMResult:
    """One classification attempt: the verdict (if valid) plus what it cost."""

    verdict: Verdict | None
    tokens_in: int = 0
    tokens_out: int = 0
    attempts: int = 0
    elapsed_s: float = 0.0
    error: str | None = None
    rate_limited: bool = False


class Classifier(Protocol):
    """Anything that can classify one failure. Tests pass fakes; providers are classes."""

    model: str
    provider: str

    def classify(
        self,
        failure: TestFailure,
        context: str,
        hint: RuleHint | None,
        changed_files: Sequence[str],
    ) -> LLMResult: ...


def verdict_schema() -> dict[str, Any]:
    """``Verdict``'s JSON schema in the strict form structured-output APIs expect:
    every property required and no extra keys."""
    schema = Verdict.model_json_schema()
    schema["required"] = list(schema["properties"])
    schema["additionalProperties"] = False
    return schema


def _strip_fences(text: str) -> str:
    """Small models sometimes wrap JSON in ```json fences despite instructions."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text.strip()


def parse_verdict(text: str, changed_files: Sequence[str]) -> Verdict:
    """Validate a reply. Raises ``ValidationError`` (or ``ValueError``) if invalid.

    Files the model names that are not in the PR are dropped: the model may only
    point at real changes.
    """
    verdict = Verdict.model_validate_json(_strip_fences(text))
    allowed = set(changed_files)
    real = [f for f in verdict.related_changed_files if f in allowed]
    if real != verdict.related_changed_files:
        verdict = verdict.model_copy(update={"related_changed_files": real})
    return verdict


class OpenAICompatClassifier:
    """Classifier for any OpenAI-compatible endpoint (Ollama, GitHub Models)."""

    def __init__(self, settings: LLMSettings, client: OpenAI | None = None) -> None:
        self.settings = settings
        self.model = settings.model
        self.provider = settings.provider
        self._format = settings.response_format
        self._client = client or OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=settings.timeout_s,
            max_retries=settings.max_retries,
        )

    def _response_format(self) -> ResponseFormatJSONSchema | ResponseFormatJSONObject:
        if self._format == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {"name": "verdict", "schema": verdict_schema(), "strict": True},
            }
        return {"type": "json_object"}

    def _complete(self, messages: list[ChatCompletionMessageParam]) -> tuple[str, int, int]:
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                temperature=0,
                messages=messages,
                response_format=self._response_format(),
            )
        except openai.BadRequestError:
            if self._format != "json_schema":
                raise
            # Some providers/models reject json_schema; fall back to plain JSON mode
            # (the schema is also described in the system prompt) for this and later calls.
            self._format = "json_object"
            return self._complete(messages)
        usage = resp.usage
        text = (resp.choices[0].message.content or "") if resp.choices else ""
        return (
            text,
            (usage.prompt_tokens if usage else 0),
            (usage.completion_tokens if usage else 0),
        )

    def classify(
        self,
        failure: TestFailure,
        context: str,
        hint: RuleHint | None,
        changed_files: Sequence[str],
    ) -> LLMResult:
        start = time.monotonic()
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_message(failure.id, context, hint, changed_files),
            },
        ]
        tokens_in = tokens_out = attempts = 0

        def result(verdict: Verdict | None, error: str | None = None, **kw: Any) -> LLMResult:
            return LLMResult(
                verdict=verdict,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                attempts=attempts,
                elapsed_s=round(time.monotonic() - start, 3),
                error=error,
                **kw,
            )

        for attempt in range(2):  # first try + one repair
            attempts = attempt + 1
            try:
                text, t_in, t_out = self._complete(messages)
            except openai.RateLimitError:
                return result(
                    None, "LLM rate-limited; showing rule-based verdict", rate_limited=True
                )
            except openai.APIError as e:  # connection, timeout, 4xx/5xx
                return result(None, f"LLM unavailable ({type(e).__name__})")
            tokens_in += t_in
            tokens_out += t_out
            try:
                return result(parse_verdict(text, changed_files))
            except (ValidationError, ValueError, json.JSONDecodeError) as e:
                messages.append({"role": "assistant", "content": text})
                messages.append(
                    {
                        "role": "user",
                        "content": f"Your reply was invalid: {str(e)[:500]}\n"
                        "Reply again with one valid JSON object only.",
                    }
                )
        return result(None, "LLM output was invalid twice")
