from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def sha256(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_in_toto_statement(
    *,
    subjects: Mapping[str, str],
    materials: Mapping[str, str],
    commands: list[str],
) -> dict[str, Any]:
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [
            {"name": name, "digest": {"sha256": digest.removeprefix("sha256:")}}
            for name, digest in sorted(subjects.items())
        ],
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://openpine.invalid/build/ast2python-stage4/v1",
                "externalParameters": {"commands": commands},
                "resolvedDependencies": [
                    {"uri": name, "digest": {"sha256": digest.removeprefix("sha256:")}}
                    for name, digest in sorted(materials.items())
                ],
            },
            "runDetails": {
                "builder": {"id": "openai-container-local-stage4"},
                "metadata": {"invocationId": "UNCOMMITTED_LOCAL_BUILD"},
            },
        },
    }
