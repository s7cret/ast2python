"""Stage 2.10: compiler target and package version stay bound to the publication lock."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pine2ast.hardening.language_publication import (
    LanguagePublicationError,
    load_language_publication,
    observe_language_publication,
    verify_language_publication,
)

import ast2python
from ast2python.lowering import load_pinelib_target_manifest

LOCAL_LOCK = (
    Path(__file__).resolve().parents[1] / "ast2python/admission/stage2_10_language_publication.json"
)


def test_stage210_compiler_lock_files_are_identical():
    published = json.loads(LOCAL_LOCK.read_text())
    assert published == load_language_publication()


def test_stage210_compiler_target_matches_publication():
    manifest = load_pinelib_target_manifest()
    observed = observe_language_publication(
        ast2python_version=ast2python.__version__,
        compiler_target_hash=manifest.content_hash,
        compiler_target_name=manifest.target_name,
        compiler_target_version=manifest.target_version,
    )
    report = verify_language_publication(observation=observed)
    assert report["status"] == "verified_local"


def test_stage210_unpublished_compiler_mapping_stops_publication():
    manifest = load_pinelib_target_manifest()
    observed = observe_language_publication(
        ast2python_version=ast2python.__version__,
        compiler_target_hash="sha256:" + "f" * 64,
        compiler_target_name=manifest.target_name,
        compiler_target_version=manifest.target_version,
    )
    with pytest.raises(LanguagePublicationError, match="compiler_target_hash"):
        verify_language_publication(observation=observed)
