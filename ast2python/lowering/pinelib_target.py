from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from pathlib import Path
from typing import Any

from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError
from ast2python.lowering.target import TargetManifest, load_reference_target_manifest


def _load_source(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        text = files("pinelib.abi").joinpath("target_manifest.json").read_text(encoding="utf-8")
    else:
        text = Path(path).read_text(encoding="utf-8")
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise BundleInvariantError(
            "A2P_PINELIB_TARGET_SCHEMA",
            "PineLib target manifest must be a JSON object",
        )
    raw: dict[str, Any] = parsed
    if raw.get("schema_id") != "pinelib.target_manifest.v2" or raw.get("schema_version") != "2.0.0":
        raise BundleInvariantError(
            "A2P_PINELIB_TARGET_SCHEMA",
            "exact PineLib target manifest v2 is required",
        )
    body = {key: value for key, value in raw.items() if key != "content_hash"}
    expected = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    if raw.get("content_hash") != expected:
        raise BundleInvariantError(
            "A2P_PINELIB_TARGET_HASH",
            "PineLib target manifest content hash mismatch",
        )
    return raw


def load_pinelib_target_manifest(path: str | Path | None = None) -> TargetManifest:
    source = _load_source(path)
    reference = load_reference_target_manifest()
    operation_rows = {name: reference.operations[name].to_dict() for name in reference.operations}
    bindings: dict[tuple[str, str, str], dict[str, Any]] = {}
    value_bindings: dict[str, dict[str, Any]] = {}
    imports = set(reference.allowed_imports) | {
        "pinelib.abi",
        "pinelib.events.common",
    }
    capabilities = set(reference.capabilities)

    compiler_operations = source.get("compiler_operations")
    if not isinstance(compiler_operations, list):
        raise BundleInvariantError(
            "A2P_PINELIB_COMPILER_OPERATIONS",
            "PineLib target manifest must declare compiler operations",
        )
    for raw_operation in compiler_operations:
        if not isinstance(raw_operation, dict):
            raise BundleInvariantError(
                "A2P_PINELIB_COMPILER_OPERATION",
                "compiler operation row must be an object",
            )
        name = raw_operation.get("name")
        expected_operation = operation_rows.get(str(name))
        callable_path = raw_operation.get("abi_callable")
        parameter_bindings = raw_operation.get("parameter_bindings")
        if (
            expected_operation is None
            or not isinstance(callable_path, str)
            or "." not in callable_path
            or not isinstance(parameter_bindings, list)
        ):
            raise BundleInvariantError(
                "A2P_PINELIB_COMPILER_OPERATION",
                "compiler operation lacks an exact reference policy or ABI callable",
            )
        if (
            raw_operation.get("evaluation") != expected_operation["evaluation"]
            or raw_operation.get("effect") != expected_operation["effect"]
        ):
            raise BundleInvariantError(
                "A2P_PINELIB_COMPILER_OPERATION_POLICY",
                "PineLib compiler operation policy differs from lowering policy",
            )
        operation_module, operation_name = callable_path.rsplit(".", 1)
        if not operation_module.startswith("pinelib.") or not operation_name.isidentifier():
            raise BundleInvariantError(
                "A2P_PINELIB_COMPILER_OPERATION",
                "compiler operation ABI callable is invalid",
            )
        operation_rows[str(name)] = {
            **expected_operation,
            "python_module": operation_module,
            "python_name": operation_name,
            "parameter_bindings": parameter_bindings,
        }
        imports.add(operation_module)

    rows = source.get("rows")
    if not isinstance(rows, list):
        raise BundleInvariantError("A2P_PINELIB_TARGET_ROWS", "PineLib rows must be an array")
    for row in rows:
        if not isinstance(row, dict):
            continue
        disposition = row.get("disposition")
        row_capabilities = row.get("capabilities", [])
        if disposition == "TARGET_DIRECT" and isinstance(row_capabilities, list):
            capabilities.update(str(item) for item in row_capabilities if isinstance(item, str))
        source_symbols = {
            str(item)
            for item in row.get("source_symbol_ids", [])
            if isinstance(item, str) and item.startswith("pine:") and "#" not in item
        }
        if row.get("category") == "constants":
            source_symbols.update(
                "pine:variable:" + symbol.removeprefix("pine:constant:")
                for symbol in tuple(source_symbols)
                if symbol.startswith("pine:constant:")
            )
        symbol_id = row.get("symbol_id")
        if isinstance(symbol_id, str):
            source_symbols.add(symbol_id)
        callable_path = row.get("abi_callable")
        python_module: str | None = None
        python_name: str | None = None
        delegation_owner: str | None = None
        delegation_schema_id: str | None = None
        delegation_capability_id: str | None = None
        if disposition == "TARGET_DIRECT":
            if not isinstance(callable_path, str) or "." not in callable_path:
                raise BundleInvariantError(
                    "A2P_PINELIB_TARGET_CALLABLE",
                    "direct PineLib row lacks an exact ABI callable",
                )
            python_module, python_name = callable_path.rsplit(".", 1)
            imports.add(python_module)
        elif disposition == "TARGET_DELEGATED":
            delegation = row.get("delegation")
            if not isinstance(delegation, dict) or set(delegation) != {
                "owner",
                "schema_id",
                "capability_id",
            }:
                raise BundleInvariantError(
                    "A2P_PINELIB_TARGET_DELEGATION",
                    "delegated PineLib row lacks exact host identity",
                )
            delegation_owner = delegation.get("owner")
            delegation_schema_id = delegation.get("schema_id")
            delegation_capability_id = delegation.get("capability_id")
            if not all(
                isinstance(item, str) and item
                for item in (
                    delegation_owner,
                    delegation_schema_id,
                    delegation_capability_id,
                )
            ):
                raise BundleInvariantError(
                    "A2P_PINELIB_TARGET_DELEGATION",
                    "delegated PineLib host identity is incomplete",
                )
        if row.get("category") in {"variables", "constants"}:
            if disposition not in {
                "TARGET_DIRECT",
                "TARGET_DELEGATED",
                "UNSUPPORTED_FAIL_CLOSED",
            }:
                raise BundleInvariantError(
                    "A2P_PINELIB_VALUE_DISPOSITION",
                    "PineLib variable row lacks an exact disposition",
                )
            parameter_bindings = row.get("parameter_bindings", [])
            if not isinstance(parameter_bindings, list):
                raise BundleInvariantError(
                    "A2P_PINELIB_TARGET_PARAMETERS",
                    "PineLib variable row lacks parameter bindings",
                )
            versions = row.get("version_availability")
            if not isinstance(versions, list) or not versions:
                raise BundleInvariantError(
                    "A2P_PINELIB_TARGET_VERSIONS",
                    "PineLib variable row lacks version availability",
                )
            return_row = row.get("return")
            return_type = (
                str(return_row.get("runtime_type") or return_row.get("pine_type") or "unknown")
                if isinstance(return_row, dict)
                else "unknown"
            )
            candidate_value = {
                "symbol_id": "",
                "disposition": disposition,
                "python_name": python_name,
                "python_module": python_module,
                "parameter_bindings": parameter_bindings,
                "return_type": return_type,
                "supported_pine_versions": sorted(set(versions)),
                "diagnostic": row.get("diagnostic"),
            }
            if disposition == "TARGET_DELEGATED":
                candidate_value.update(
                    {
                        "delegation_owner": delegation_owner,
                        "delegation_schema_id": delegation_schema_id,
                        "delegation_capability_id": delegation_capability_id,
                    }
                )
            for source_symbol in sorted(source_symbols):
                candidate = dict(candidate_value)
                candidate["symbol_id"] = source_symbol
                existing = value_bindings.get(source_symbol)
                if existing is not None and existing != candidate:
                    raise BundleInvariantError(
                        "A2P_PINELIB_VALUE_DUPLICATE",
                        "conflicting PineLib value projection",
                    )
                value_bindings[source_symbol] = candidate
            continue
        if disposition not in {"TARGET_DIRECT", "TARGET_DELEGATED"}:
            continue
        row_call_form = row.get("call_form")
        call_forms = (
            ("METHOD",)
            if row_call_form == "method"
            else (
                ("FUNCTION", "NAMESPACE_FUNCTION")
                if row_call_form == "namespace_function"
                else ("FUNCTION",)
            )
        )
        versions = row.get("version_availability")
        if not isinstance(versions, list) or not versions:
            raise BundleInvariantError(
                "A2P_PINELIB_TARGET_VERSIONS",
                "PineLib call row lacks version availability",
            )
        parameter_rows = row.get("parameters", [])
        parameters = [
            str(item["name"])
            for item in parameter_rows
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
        parameter_bindings = row.get("parameter_bindings", [])
        if not isinstance(parameter_bindings, list):
            raise BundleInvariantError(
                "A2P_PINELIB_TARGET_PARAMETERS",
                "direct PineLib row lacks parameter bindings",
            )
        return_row = row.get("return")
        return_type = (
            str(
                return_row.get("runtime_type")
                or return_row.get("pine_type")
                or return_row.get("type")
                or "unknown"
            )
            if isinstance(return_row, dict)
            else "unknown"
        )
        producer_overloads = [
            str(item) for item in row.get("producer_overload_ids", []) if isinstance(item, str)
        ]
        for source_symbol in sorted(source_symbols):
            overloads = [
                item for item in producer_overloads if item.startswith(source_symbol + "#")
            ] or [source_symbol + "#canonical"]
            for overload_id in overloads:
                for call_form in call_forms:
                    key = (source_symbol, overload_id, call_form)
                    candidate = {
                        "symbol_id": source_symbol,
                        "overload_id": overload_id,
                        "call_form": call_form,
                        "python_name": (
                            "dispatch_delegated"
                            if disposition == "TARGET_DELEGATED"
                            else python_name
                        ),
                        "parameters": parameters,
                        "return_type": return_type,
                        "state_model": str(row.get("state_model") or "NONE"),
                        "supported_pine_versions": sorted(set(versions)),
                    }
                    if disposition == "TARGET_DIRECT":
                        candidate.update(
                            {
                                "python_module": python_module,
                                "parameter_bindings": parameter_bindings,
                            }
                        )
                    else:
                        candidate.update(
                            {
                                "disposition": disposition,
                                "delegation_owner": delegation_owner,
                                "delegation_schema_id": delegation_schema_id,
                                "delegation_capability_id": delegation_capability_id,
                            }
                        )
                    existing = bindings.get(key)
                    if existing is not None and existing != candidate:
                        raise BundleInvariantError(
                            "A2P_PINELIB_TARGET_DUPLICATE",
                            "conflicting PineLib call projection",
                        )
                    bindings[key] = candidate

    body: dict[str, Any] = {
        "schema_id": "ast2python.target_manifest.v1",
        "schema_version": "1.0.0",
        "target_name": "pinelib",
        "target_version": str(source["content_hash"]),
        "operations": [operation_rows[name] for name in sorted(operation_rows)],
        "call_bindings": [bindings[key] for key in sorted(bindings)],
        "value_bindings": [value_bindings[key] for key in sorted(value_bindings)],
        "capabilities": sorted(capabilities),
        "allowed_imports": sorted(imports),
        "release_acceptance": "EXACT_PINELIB_TARGET_MANIFEST_V2",
    }
    body["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return TargetManifest.from_mapping(body)
