from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_spdx(*, wheel: Path | None = None) -> dict[str, Any]:
    checksums = [] if wheel is None else [{"algorithm": "SHA256", "checksumValue": _sha(wheel)}]
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "ast2python-5.0.0rc6-stage4",
        "documentNamespace": "https://openpine.invalid/sbom/ast2python/5.0.0rc6/stage4",
        "packages": [
            {
                "SPDXID": "SPDXRef-Package-ast2python",
                "name": "ast2python",
                "versionInfo": "5.0.0rc6",
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "MIT",
                "licenseDeclared": "MIT",
                "checksums": checksums,
            }
        ],
    }


def build_cyclonedx(*, wheel: Path | None = None) -> dict[str, Any]:
    hashes = [] if wheel is None else [{"alg": "SHA-256", "content": _sha(wheel)}]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {"component": {"type": "library", "name": "ast2python", "version": "5.0.0rc6"}},
        "components": [
            {
                "type": "library",
                "name": "ast2python",
                "version": "5.0.0rc6",
                "licenses": [{"license": {"id": "MIT"}}],
                "hashes": hashes,
            }
        ],
    }
