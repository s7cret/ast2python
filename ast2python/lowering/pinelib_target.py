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
        "pinelib.core.values",
    }
    capabilities = set(reference.capabilities)
    registry_contract = {
        "revision": 1,
        "schema_id": "pinelib.nominal_registry.v1",
        "identity": "source-declaration",
        "admission": "module-literal-before-execution",
        "min_pine_version": 5,
    }
    # JSON equality preserves primitive types; Python equality would accept
    # True for revision 1 or 5.0 for the exact integer version boundary.
    if canonical_json_bytes(source.get("compiled_nominal_registry")) == canonical_json_bytes(
        registry_contract
    ):
        capabilities.add("compiler.nominal_registry.v1")
    if source.get("compiled_nominal_types") == {
        "revision": 1,
        "identity": "source-declaration",
        "udt_binding_modes": ["default", "var", "varip"],
        "udt_fields": "declared-schema-field-rollback",
        "enum_storage": "nominal-portable-values",
        "min_pine_version": 5,
    }:
        capabilities.add("compiler.nominal_types.v1")
    if source.get("compiled_reference_storage") == {
        "revision": 1,
        "identity": "callback-and-occurrence",
        "binding_modes": ["default", "var"],
        "reference_history_min_version": {"array": 5},
    }:
        capabilities.add("compiler.reference_bindings.v1")
    if source.get("compiled_loop_values") == {
        "revision": 1,
        "budget": "shared-callback",
        "for_in": "live-array",
        "empty_tuple": "typed-elements",
    }:
        capabilities.add("compiler.loop_values.v1")

    if source.get("compiled_collection_iteration") == {
        "revision": 1,
        "map": "insertion-order-stable-keys-live-values",
        "matrix": "live-size-row-arrays",
        "min_pine_version": 5,
    }:
        capabilities.add("compiler.collection_iteration.v1")

    varip = source.get("compiled_varip_reference_storage")
    varip_contract = {
        "revision": 1,
        "policy": "per-object-transactional-persistence",
        "kinds": ["array", "matrix", "map"],
        "element_types": ["int", "float", "bool", "color", "string"],
        "min_pine_version": 5,
    }
    if varip == varip_contract:
        capabilities.add("compiler.varip_reference_bindings.v1")

    nominal_arrays = {
        "revision": 1,
        "registry_schema_id": "pinelib.nominal_registry.v1",
        "element_type": "udt",
        "field_profile": "fundamentals-and-ordinary-fundamental-array-matrix",
        "persistence": "array-elements-and-declared-varip-fields",
        "min_pine_version": 5,
    }
    if (
        canonical_json_bytes(source.get("compiled_varip_nominal_arrays")) == canonical_json_bytes(nominal_arrays)
        and canonical_json_bytes(varip) == canonical_json_bytes(varip_contract)
        and {"compiler.nominal_registry.v1", "compiler.varip_reference_bindings.v1"} <= capabilities
    ):
        capabilities.add("compiler.varip_nominal_arrays.v1")

    compiler_operations = source.get("compiler_operations")
    if not isinstance(compiler_operations, list):
        raise BundleInvariantError(
            "A2P_PINELIB_COMPILER_OPERATIONS",
            "PineLib target manifest must declare compiler operations",
        )
    # Only these three opcodes call runtime primitives. Other reference rows
    # describe compiler-owned structural lowering, not fallback implementations.
    required_primitives = {"operator.binary", "operator.unary", "series.history"}
    names = [row.get("name") for row in compiler_operations if isinstance(row, dict)]
    if len(names) != len(compiler_operations) or any(type(name) is not str for name in names):
        raise BundleInvariantError("A2P_PINELIB_COMPILER_OPERATION", "malformed operation names")
    if len(set(names)) != len(names):
        raise BundleInvariantError("A2P_PINELIB_COMPILER_OPERATION", "duplicate compiler operation")
    missing = required_primitives.difference(names)
    if missing:
        raise BundleInvariantError(
            "A2P_PINELIB_REQUIRED_OPERATION",
            "exact target lacks required runtime primitives; reference fallback is forbidden",
            details={"missing": sorted(missing)},
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
    historical_rows = source.get("historical_call_bindings", [])
    if not isinstance(historical_rows, list):
        raise BundleInvariantError(
            "A2P_PINELIB_HISTORICAL_BINDINGS", "historical call bindings must be an array"
        )
    for row in historical_rows:
        if (
            not isinstance(row, dict)
            or row.get("disposition") != "TARGET_DIRECT"
            or row.get("category") != "functions"
            or row.get("call_form") != "global_function"
            or row.get("producer_call_forms") != ["FUNCTION"]
            or not isinstance(row.get("source_symbol_ids"), list)
            or not row["source_symbol_ids"]
            or any(
                not isinstance(symbol, str)
                or not symbol.startswith("pine:function:")
                or "#" in symbol
                for symbol in row["source_symbol_ids"]
            )
            or not isinstance(row.get("producer_overload_ids"), list)
            or not row["producer_overload_ids"]
            or any(
                not isinstance(overload, str)
                or not any(overload.startswith(symbol + "#") for symbol in row["source_symbol_ids"])
                for overload in row["producer_overload_ids"]
            )
            or not isinstance(row.get("version_availability"), list)
            or not row["version_availability"]
            or any(
                type(version) is not int or version not in range(1, 5)
                for version in row["version_availability"]
            )
            or len(set(row["version_availability"])) != len(row["version_availability"])
        ):
            raise BundleInvariantError(
                "A2P_PINELIB_HISTORICAL_BINDINGS",
                "historical bindings require exact direct global producer identities and versions",
            )
    historical_row_ids = {id(row) for row in historical_rows}
    for row in [*rows, *historical_rows]:
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
        default_call_forms = (
            ("METHOD",)
            if row_call_form == "method"
            else (
                ("FUNCTION", "NAMESPACE_FUNCTION")
                if row_call_form == "namespace_function"
                else ("FUNCTION",)
            )
        )
        call_forms = row.get("producer_call_forms", default_call_forms)
        if (
            not isinstance(call_forms, (list, tuple))
            or not call_forms
            or any(form not in default_call_forms for form in call_forms)
            or len(set(call_forms)) != len(call_forms)
        ):
            raise BundleInvariantError(
                "A2P_PINELIB_TARGET_CALL_FORMS",
                "producer call forms must be an exact nonempty subset of the row call forms",
            )
        versions = row.get("version_availability")
        if not isinstance(versions, list) or not versions:
            raise BundleInvariantError(
                "A2P_PINELIB_TARGET_VERSIONS",
                "PineLib call row lacks version availability",
            )
        from ast2python.lowering.qualifiers import project_parameter_qualifiers

        parameter_rows = row.get("parameters", [])
        parameter_qualifiers = project_parameter_qualifiers(parameter_rows)
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
            ]
            if not overloads and id(row) not in historical_row_ids:
                overloads = [source_symbol + "#canonical"]
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
                        "parameter_qualifiers": dict(parameter_qualifiers),
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
