from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ast2python.errors import BundleInvariantError
from ast2python.version import REQUIRED_PINE2AST_VERSION

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class ProducerIdentity:
    name: str
    version: str
    commit: str | None

    @property
    def commit_bound(self) -> bool:
        return self.commit is not None

    def to_dict(self) -> dict[str, str | bool | None]:
        return {
            "name": self.name,
            "version": self.version,
            "commit": self.commit,
            "commit_bound": self.commit_bound,
        }


def validate_producer_identity(value: Any) -> ProducerIdentity:
    if not isinstance(value, Mapping):
        raise BundleInvariantError(
            "A2P_PRODUCER_TYPE", "producer must be an object", path="$.producer"
        )
    if set(value) != {"name", "version", "commit"}:
        raise BundleInvariantError(
            "A2P_PRODUCER_FIELDS",
            "producer must contain exactly name, version and commit",
            path="$.producer",
        )
    name = value.get("name")
    version = value.get("version")
    commit = value.get("commit")
    if name != "pine2ast":
        raise BundleInvariantError(
            "A2P_PRODUCER_NAME",
            f"expected producer 'pine2ast', got {name!r}",
            path="$.producer.name",
        )
    if version != REQUIRED_PINE2AST_VERSION:
        raise BundleInvariantError(
            "A2P_PRODUCER_VERSION",
            f"expected Pine2AST {REQUIRED_PINE2AST_VERSION}, got {version!r}",
            path="$.producer.version",
        )
    if commit is not None and (not isinstance(commit, str) or _SHA_RE.fullmatch(commit) is None):
        raise BundleInvariantError(
            "A2P_PRODUCER_COMMIT",
            "producer commit must be null or an exact lowercase 40-character Git SHA",
            path="$.producer.commit",
        )
    return ProducerIdentity(name=name, version=version, commit=commit)
