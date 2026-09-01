from __future__ import annotations

from copy import deepcopy

import pytest
from pine2ast.hardening.model import content_hash

from ast2python import CompilationMode, admit_consumer_bundle
from ast2python.errors import BundleAdmissionError
from tests.conftest import load_bundle


def reseal(bundle: dict) -> dict:
    bundle = deepcopy(bundle)
    body = {key: value for key, value in bundle.items() if key != "content_hash"}
    bundle["content_hash"] = content_hash(body)
    return bundle


def test_blocking_diagnostics_fail_production_but_can_be_inspected() -> None:
    bundle = load_bundle(6)
    bundle["diagnostics"] = [
        {
            "severity": "ERROR",
            "code": "P2A_TEST",
            "message": "test blocking diagnostic",
            "span": {
                "start_offset": 0,
                "end_offset": 0,
                "start_line": 1,
                "start_col": 1,
                "end_line": 1,
                "end_col": 1,
            },
        }
    ]
    bundle = reseal(bundle)
    with pytest.raises(BundleAdmissionError, match="A2P_BLOCKING_DIAGNOSTICS"):
        admit_consumer_bundle(bundle, mode=CompilationMode.PRODUCTION)
    admitted = admit_consumer_bundle(bundle, mode=CompilationMode.ANALYSIS)
    assert admitted.mode is CompilationMode.ANALYSIS
    assert admitted.runnable_output_allowed is False
