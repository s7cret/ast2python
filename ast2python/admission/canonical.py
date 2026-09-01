from __future__ import annotations

import json
import stat
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeAlias

from ast2python.admission.limits import AdmissionLimits
from ast2python.errors import BundleLimitError, BundleSourceError

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
BundleInput: TypeAlias = Mapping[str, Any] | bytes | bytearray | memoryview | Path


def _reject_constant(value: str) -> None:
    raise BundleSourceError("A2P_JSON_NONFINITE", f"non-finite JSON number is forbidden: {value}")


def _pairs_to_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleSourceError(
                "A2P_JSON_DUPLICATE_KEY",
                f"duplicate JSON key: {key!r}",
                path=f"$.{key}",
            )
        result[key] = value
    return result


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except RecursionError as exc:
        raise BundleLimitError(
            "A2P_JSON_DEPTH",
            "JSON nesting exceeds the canonicalizer recursion boundary",
        ) from exc
    except ValueError as exc:
        if "integer string conversion" in str(exc):
            raise BundleLimitError(
                "A2P_JSON_INTEGER_LIMIT",
                "JSON integer exceeds the runtime conversion limit",
            ) from exc
        raise BundleSourceError("A2P_JSON_NOT_CANONICALIZABLE", str(exc)) from exc
    except TypeError as exc:
        raise BundleSourceError("A2P_JSON_NOT_CANONICALIZABLE", str(exc)) from exc


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return _canonical_json(value).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise BundleSourceError(
            "A2P_JSON_ENCODING",
            "bundle contains Unicode that cannot be encoded as strict UTF-8",
        ) from exc


def _load_bytes(raw: bytes, limits: AdmissionLimits) -> dict[str, Any]:
    if len(raw) > limits.max_bundle_bytes:
        raise BundleLimitError(
            "A2P_BUNDLE_TOO_LARGE",
            f"bundle has {len(raw)} bytes; limit is {limits.max_bundle_bytes}",
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleSourceError("A2P_JSON_ENCODING", "bundle must be strict UTF-8") from exc
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_pairs_to_object,
            parse_constant=_reject_constant,
        )
    except BundleSourceError:
        raise
    except json.JSONDecodeError as exc:
        raise BundleSourceError(
            "A2P_JSON_INVALID",
            exc.msg,
            path=f"$[line={exc.lineno},column={exc.colno}]",
        ) from exc
    except RecursionError as exc:
        raise BundleLimitError(
            "A2P_JSON_DEPTH",
            "JSON nesting exceeds the parser recursion boundary",
        ) from exc
    except ValueError as exc:
        raise BundleLimitError(
            "A2P_JSON_INTEGER_LIMIT",
            "JSON integer exceeds the runtime conversion limit",
        ) from exc
    if not isinstance(parsed, dict):
        raise BundleSourceError("A2P_BUNDLE_ROOT_TYPE", "bundle root must be a JSON object")
    return parsed


def load_bundle_input(source: BundleInput, limits: AdmissionLimits) -> tuple[dict[str, Any], bytes]:
    if isinstance(source, Path):
        try:
            source_stat = source.lstat()
        except OSError as exc:
            raise BundleSourceError(
                "A2P_BUNDLE_PATH", f"cannot stat bundle path: {source}"
            ) from exc
        if stat.S_ISLNK(source_stat.st_mode):
            raise BundleSourceError(
                "A2P_BUNDLE_PATH_SYMLINK",
                f"bundle path must not be a symbolic link: {source}",
            )
        if not stat.S_ISREG(source_stat.st_mode):
            raise BundleSourceError(
                "A2P_BUNDLE_PATH",
                f"bundle path must be a regular file: {source}",
            )
        size = source_stat.st_size
        if size > limits.max_bundle_bytes:
            raise BundleLimitError(
                "A2P_BUNDLE_TOO_LARGE",
                f"bundle has {size} bytes; limit is {limits.max_bundle_bytes}",
            )
        try:
            raw = source.read_bytes()
        except OSError as exc:
            raise BundleSourceError(
                "A2P_BUNDLE_PATH", f"cannot read bundle path: {source}"
            ) from exc
        if len(raw) > limits.max_bundle_bytes:
            raise BundleLimitError(
                "A2P_BUNDLE_TOO_LARGE",
                f"bundle has {len(raw)} bytes after read; limit is {limits.max_bundle_bytes}",
            )
        value = _load_bytes(raw, limits)
        return value, canonical_json_bytes(value)
    if isinstance(source, (bytes, bytearray, memoryview)):
        value = _load_bytes(bytes(source), limits)
        return value, canonical_json_bytes(value)
    if isinstance(source, str):
        raise BundleSourceError(
            "A2P_BUNDLE_STRING_AMBIGUOUS",
            "plain strings are not accepted; pass bytes for JSON or pathlib.Path for files",
        )
    if isinstance(source, Mapping):
        value = _mapping_to_plain(source, limits=limits)
        if not isinstance(value, dict):
            raise BundleSourceError("A2P_BUNDLE_ROOT_TYPE", "bundle root must be a mapping")
        raw = canonical_json_bytes(value)
        if len(raw) > limits.max_bundle_bytes:
            raise BundleLimitError(
                "A2P_BUNDLE_TOO_LARGE",
                f"canonical bundle has {len(raw)} bytes; limit is {limits.max_bundle_bytes}",
            )
        return value, raw
    raise BundleSourceError(
        "A2P_BUNDLE_SOURCE_TYPE",
        f"expected Mapping, bytes or pathlib.Path; got {type(source).__name__}",
    )


def _mapping_to_plain(
    value: Any,
    *,
    limits: AdmissionLimits,
    path: str = "$",
    depth: int = 1,
    active_containers: set[int] | None = None,
) -> Any:
    if depth > limits.max_json_depth:
        raise BundleLimitError(
            "A2P_JSON_DEPTH",
            f"JSON depth exceeds {limits.max_json_depth}",
            path=path,
        )
    active = set() if active_containers is None else active_containers
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active:
            raise BundleSourceError(
                "A2P_JSON_CYCLE",
                "cyclic mappings are not valid JSON",
                path=path,
            )
        active.add(identity)
        try:
            result: dict[str, Any] = {}
            for key, child in value.items():
                if not isinstance(key, str):
                    raise BundleSourceError(
                        "A2P_JSON_KEY_TYPE",
                        "all JSON object keys must be strings",
                        path=path,
                    )
                if len(key) > limits.max_string_length:
                    raise BundleLimitError(
                        "A2P_STRING_TOO_LONG",
                        f"object key length exceeds {limits.max_string_length}",
                        path=path,
                    )
                result[key] = _mapping_to_plain(
                    child,
                    limits=limits,
                    path=f"{path}.{key}",
                    depth=depth + 1,
                    active_containers=active,
                )
            return result
        finally:
            active.remove(identity)
    if isinstance(value, list):
        identity = id(value)
        if identity in active:
            raise BundleSourceError(
                "A2P_JSON_CYCLE",
                "cyclic arrays are not valid JSON",
                path=path,
            )
        active.add(identity)
        try:
            return [
                _mapping_to_plain(
                    child,
                    limits=limits,
                    path=f"{path}[{index}]",
                    depth=depth + 1,
                    active_containers=active,
                )
                for index, child in enumerate(value)
            ]
        finally:
            active.remove(identity)
    if value is None or type(value) in {bool, int, float, str}:
        if isinstance(value, str) and len(value) > limits.max_string_length:
            raise BundleLimitError(
                "A2P_STRING_TOO_LONG",
                f"string length exceeds {limits.max_string_length}",
                path=path,
            )
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            raise BundleSourceError(
                "A2P_JSON_NONFINITE",
                "non-finite JSON number is forbidden",
                path=path,
            )
        return value
    raise BundleSourceError(
        "A2P_JSON_VALUE_TYPE",
        f"unsupported JSON value type: {type(value).__name__}",
        path=path,
    )


def enforce_generic_limits(value: Any, limits: AdmissionLimits) -> None:
    stack: list[tuple[Any, int, str]] = [(value, 1, "$")]
    total_nodes = 0
    while stack:
        current, depth, path = stack.pop()
        total_nodes += 1
        if total_nodes > limits.max_total_json_nodes:
            raise BundleLimitError(
                "A2P_JSON_NODE_LIMIT",
                f"JSON node count exceeds {limits.max_total_json_nodes}",
                path=path,
            )
        if depth > limits.max_json_depth:
            raise BundleLimitError(
                "A2P_JSON_DEPTH",
                f"JSON depth exceeds {limits.max_json_depth}",
                path=path,
            )
        if isinstance(current, str):
            if len(current) > limits.max_string_length:
                raise BundleLimitError(
                    "A2P_STRING_TOO_LONG",
                    f"string length exceeds {limits.max_string_length}",
                    path=path,
                )
        elif isinstance(current, Mapping):
            if len(current) > limits.max_container_items:
                raise BundleLimitError(
                    "A2P_CONTAINER_ITEM_LIMIT",
                    f"object item count exceeds {limits.max_container_items}",
                    path=path,
                )
            for key, child in current.items():
                if len(key) > limits.max_string_length:
                    raise BundleLimitError(
                        "A2P_STRING_TOO_LONG",
                        f"object key length exceeds {limits.max_string_length}",
                        path=path,
                    )
                stack.append((child, depth + 1, f"{path}.{key}"))
        elif isinstance(current, list):
            if len(current) > limits.max_container_items:
                raise BundleLimitError(
                    "A2P_CONTAINER_ITEM_LIMIT",
                    f"array item count exceeds {limits.max_container_items}",
                    path=path,
                )
            for index, child in enumerate(current):
                stack.append((child, depth + 1, f"{path}[{index}]"))


def freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze_json(child) for key, child in value.items()})
    if isinstance(value, list):
        return tuple(freeze_json(child) for child in value)
    return value


def thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [thaw_json(child) for child in value]
    return value
