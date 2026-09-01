from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "consumer"
PINNED_PRODUCER_COMMIT = "a" * 40


def load_bundle(version: int = 6) -> dict[str, Any]:
    return json.loads(
        (FIXTURE_ROOT / f"pine-v{version}-consumer-bundle.json").read_text(encoding="utf-8")
    )


@pytest.fixture(autouse=True)
def pin_ast2python_producer_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    import ast2python.compiler as compiler

    original = compiler.compile_consumer_bundle

    def _compile(source, *, producer_commit=None, **kwargs):  # type: ignore[no-untyped-def]
        return original(
            source,
            producer_commit=producer_commit or PINNED_PRODUCER_COMMIT,
            **kwargs,
        )

    monkeypatch.setattr(compiler, "compile_consumer_bundle", _compile)
    monkeypatch.setattr("ast2python.api.compile_consumer_bundle", _compile)


@pytest.fixture
def bundle_v6() -> dict[str, Any]:
    return load_bundle(6)


@pytest.fixture
def cloned_bundle_v6(bundle_v6: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(bundle_v6)
