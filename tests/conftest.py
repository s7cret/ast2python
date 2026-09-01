from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "consumer"


def load_bundle(version: int = 6) -> dict[str, Any]:
    return json.loads(
        (FIXTURE_ROOT / f"pine-v{version}-consumer-bundle.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def bundle_v6() -> dict[str, Any]:
    return load_bundle(6)


@pytest.fixture
def cloned_bundle_v6(bundle_v6: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(bundle_v6)
