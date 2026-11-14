import pytest
from pydantic import ValidationError

from flakehunter.models import TestFailure


def make(**overrides: object) -> TestFailure:
    data: dict[str, object] = {"id": "a::b", "suite": "a", "name": "b", "kind": "failure"}
    data.update(overrides)
    return TestFailure.model_validate(data)


def test_defaults() -> None:
    f = make()
    assert f.message == ""
    assert f.file is None
    assert f.source_format == "unknown"


def test_invalid_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        make(kind="crash")


def test_is_frozen() -> None:
    f = make()
    with pytest.raises(ValidationError):
        f.message = "changed"  # type: ignore[misc]
