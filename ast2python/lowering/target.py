from __future__ import annotations

import hashlib
import json
import keyword
from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError


@dataclass(frozen=True, slots=True)
class TargetOperation:
    name: str
    evaluation: str
    effect: str
    python_name: str
    python_module: str | None = None
    parameter_bindings: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": self.name,
            "evaluation": self.evaluation,
            "effect": self.effect,
            "python_name": self.python_name,
        }
        if self.python_module is not None:
            body["python_module"] = self.python_module
            body["parameter_bindings"] = [dict(item) for item in self.parameter_bindings]
        return body


@dataclass(frozen=True, slots=True)
class TargetCallBinding:
    symbol_id: str
    overload_id: str
    call_form: str
    python_name: str
    parameters: tuple[str, ...]
    return_type: str
    state_model: str
    supported_pine_versions: tuple[int, ...]
    python_module: str | None = None
    parameter_bindings: tuple[Mapping[str, Any], ...] = ()
    disposition: str = "TARGET_DIRECT"
    delegation_owner: str | None = None
    delegation_schema_id: str | None = None
    delegation_capability_id: str | None = None

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.symbol_id, self.overload_id, self.call_form)

    def to_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "symbol_id": self.symbol_id,
            "overload_id": self.overload_id,
            "call_form": self.call_form,
            "python_name": self.python_name,
            "parameters": list(self.parameters),
            "return_type": self.return_type,
            "state_model": self.state_model,
            "supported_pine_versions": list(self.supported_pine_versions),
        }
        if self.python_module is not None:
            body["python_module"] = self.python_module
            body["parameter_bindings"] = [dict(item) for item in self.parameter_bindings]
        if self.disposition == "TARGET_DELEGATED":
            body.update(
                {
                    "disposition": self.disposition,
                    "delegation_owner": self.delegation_owner,
                    "delegation_schema_id": self.delegation_schema_id,
                    "delegation_capability_id": self.delegation_capability_id,
                }
            )
        return body


@dataclass(frozen=True, slots=True)
class TargetValueBinding:
    symbol_id: str
    python_name: str | None
    disposition: str = "REFERENCE_RUNTIME_ATTRIBUTE"
    python_module: str | None = None
    parameter_bindings: tuple[Mapping[str, Any], ...] = ()
    return_type: str = "unknown"
    supported_pine_versions: tuple[int, ...] = (1, 2, 3, 4, 5, 6)
    diagnostic: str | None = None
    delegation_owner: str | None = None
    delegation_schema_id: str | None = None
    delegation_capability_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.disposition == "REFERENCE_RUNTIME_ATTRIBUTE":
            return {"symbol_id": self.symbol_id, "python_name": self.python_name}
        body: dict[str, Any] = {
            "symbol_id": self.symbol_id,
            "disposition": self.disposition,
            "python_name": self.python_name,
            "python_module": self.python_module,
            "parameter_bindings": [dict(item) for item in self.parameter_bindings],
            "return_type": self.return_type,
            "supported_pine_versions": list(self.supported_pine_versions),
            "diagnostic": self.diagnostic,
        }
        if self.disposition == "TARGET_DELEGATED":
            body.update(
                {
                    "delegation_owner": self.delegation_owner,
                    "delegation_schema_id": self.delegation_schema_id,
                    "delegation_capability_id": self.delegation_capability_id,
                }
            )
        return body


@dataclass(frozen=True, slots=True)
class TargetManifest:
    schema_id: str
    schema_version: str
    target_name: str
    target_version: str
    operations: Mapping[str, TargetOperation]
    call_bindings: Mapping[tuple[str, str, str], TargetCallBinding]
    value_bindings: Mapping[str, TargetValueBinding]
    capabilities: frozenset[str]
    allowed_imports: frozenset[str]
    content_hash: str
    release_acceptance: str

    def to_body_dict(self) -> dict[str, Any]:
        return {
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
            "target_name": self.target_name,
            "target_version": self.target_version,
            "operations": [self.operations[name].to_dict() for name in sorted(self.operations)],
            "call_bindings": [
                self.call_bindings[key].to_dict() for key in sorted(self.call_bindings)
            ],
            "value_bindings": [
                self.value_bindings[symbol_id].to_dict()
                for symbol_id in sorted(self.value_bindings)
            ],
            "capabilities": sorted(self.capabilities),
            "allowed_imports": sorted(self.allowed_imports),
            "release_acceptance": self.release_acceptance,
        }

    def to_dict(self) -> dict[str, Any]:
        body = self.to_body_dict()
        body["content_hash"] = self.content_hash
        return body

    def without_call_binding(self, key: tuple[str, str, str]) -> TargetManifest:
        body = self.to_body_dict()
        body["call_bindings"] = [
            row
            for row in body["call_bindings"]
            if (row["symbol_id"], row["overload_id"], row["call_form"]) != key
        ]
        body["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
        return self.from_mapping(body)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TargetManifest:
        expected = {
            "schema_id",
            "schema_version",
            "target_name",
            "target_version",
            "operations",
            "call_bindings",
            "value_bindings",
            "capabilities",
            "allowed_imports",
            "release_acceptance",
            "content_hash",
        }
        if set(value) != expected:
            raise BundleInvariantError(
                "A2P_TARGET_FIELDS",
                "target manifest fields are not exact",
                details={
                    "missing": sorted(expected - set(value)),
                    "extra": sorted(set(value) - expected),
                },
            )
        for field in (
            "schema_id",
            "schema_version",
            "target_name",
            "target_version",
            "release_acceptance",
        ):
            if not isinstance(value[field], str) or not value[field]:
                raise BundleInvariantError(
                    "A2P_TARGET_IDENTITY",
                    f"{field} must be a non-empty string",
                    path=f"$.{field}",
                )
        if not isinstance(value["content_hash"], str):
            raise BundleInvariantError("A2P_TARGET_HASH", "content_hash must be a string")
        operations_raw = value["operations"]
        call_bindings_raw = value["call_bindings"]
        value_bindings_raw = value["value_bindings"]
        capabilities = value["capabilities"]
        allowed_imports = value["allowed_imports"]
        if not isinstance(operations_raw, list):
            raise BundleInvariantError("A2P_TARGET_OPERATIONS", "operations must be an array")
        if not isinstance(call_bindings_raw, list):
            raise BundleInvariantError("A2P_TARGET_CALL_BINDINGS", "call_bindings must be an array")
        if not isinstance(value_bindings_raw, list):
            raise BundleInvariantError(
                "A2P_TARGET_VALUE_BINDINGS", "value_bindings must be an array"
            )
        if not isinstance(capabilities, list):
            raise BundleInvariantError("A2P_TARGET_CAPABILITIES", "capabilities must be an array")
        if not isinstance(allowed_imports, list):
            raise BundleInvariantError("A2P_TARGET_IMPORTS", "allowed imports must be an array")
        if (
            value["schema_id"] != "ast2python.target_manifest.v1"
            or value["schema_version"] != "1.0.0"
        ):
            raise BundleInvariantError("A2P_TARGET_SCHEMA", "unsupported target manifest schema")
        if value["release_acceptance"] not in {
            "REFERENCE_ONLY_PENDING_PINELIB_RC6",
            "EXACT_PINELIB_TARGET_MANIFEST_V2",
        }:
            raise BundleInvariantError(
                "A2P_TARGET_RELEASE_PROOF",
                "unknown target release acceptance proof",
                path="$.release_acceptance",
            )
        operation_names: list[str] = []
        for index, raw in enumerate(operations_raw):
            operation_fields = {"name", "evaluation", "effect", "python_name"}
            exact_operation_fields = operation_fields | {
                "python_module",
                "parameter_bindings",
            }
            if not isinstance(raw, Mapping) or set(raw) not in {
                frozenset(operation_fields),
                frozenset(exact_operation_fields),
            }:
                raise BundleInvariantError(
                    "A2P_TARGET_OPERATION",
                    "operation fields are not exact",
                    path=f"$.operations[{index}]",
                )
            name = raw["name"]
            if not isinstance(name, str) or not name:
                raise BundleInvariantError(
                    "A2P_TARGET_OPERATION_ID", "operation name must be non-empty"
                )
            operation_names.append(name)
        if len(operation_names) != len(set(operation_names)):
            raise BundleInvariantError(
                "A2P_TARGET_OPERATION_ID",
                "operation names must be unique",
                path="$.operations",
            )
        if operation_names != sorted(operation_names):
            raise BundleInvariantError(
                "A2P_TARGET_OPERATION_ORDER",
                "operation names must be sorted",
                path="$.operations",
            )
        operations: dict[str, TargetOperation] = {}
        for raw in operations_raw:
            name = raw["name"]
            evaluation = raw["evaluation"]
            effect = raw["effect"]
            python_name = raw["python_name"]
            if not isinstance(evaluation, str) or evaluation not in {"eager", "lazy", "structural"}:
                raise BundleInvariantError(
                    "A2P_TARGET_EVALUATION", "unknown operation evaluation mode"
                )
            if not isinstance(effect, str) or effect not in {
                "pure",
                "state",
                "request",
                "strategy",
                "visual",
                "control",
                "declaration",
            }:
                raise BundleInvariantError("A2P_TARGET_EFFECT", "unknown operation effect")
            if (
                not isinstance(python_name, str)
                or not python_name.isidentifier()
                or keyword.iskeyword(python_name)
            ):
                raise BundleInvariantError(
                    "A2P_TARGET_PYTHON_NAME", "invalid operation Python binding"
                )
            python_module = raw.get("python_module")
            if python_module is not None and (
                not isinstance(python_module, str)
                or not python_module.startswith("pinelib.")
                or not all(part.isidentifier() for part in python_module.split("."))
            ):
                raise BundleInvariantError(
                    "A2P_TARGET_OPERATION_MODULE", "invalid exact PineLib primitive module"
                )
            parameter_bindings_raw = raw.get("parameter_bindings", [])
            if python_module is not None:
                if not isinstance(parameter_bindings_raw, list):
                    raise BundleInvariantError(
                        "A2P_TARGET_OPERATION_PARAMETERS",
                        "exact operation parameter bindings must be an array",
                    )
                operation_indexes: list[int] = []
                for binding in parameter_bindings_raw:
                    if not isinstance(binding, Mapping):
                        raise BundleInvariantError(
                            "A2P_TARGET_OPERATION_PARAMETERS",
                            "operation parameter binding must be an object",
                        )
                    binding_kind = binding.get("binding")
                    if binding_kind == "INJECTED":
                        valid = (
                            set(binding) == {"abi_parameter", "binding", "source"}
                            and binding.get("source") == "RUNTIME_TRANSACTION"
                        )
                    elif binding_kind == "OPERATION_ARGUMENT":
                        valid = (
                            set(binding) == {"abi_parameter", "binding", "source_index"}
                            and type(binding.get("source_index")) is int
                        )
                        if valid:
                            operation_indexes.append(int(binding["source_index"]))
                    else:
                        valid = False
                    if not valid:
                        raise BundleInvariantError(
                            "A2P_TARGET_OPERATION_PARAMETERS",
                            "unknown exact operation parameter binding",
                        )
                if operation_indexes != list(range(len(operation_indexes))):
                    raise BundleInvariantError(
                        "A2P_TARGET_OPERATION_PARAMETERS",
                        "operation argument indexes must be contiguous",
                    )
            operations[name] = TargetOperation(
                name,
                evaluation,
                effect,
                python_name,
                python_module,
                tuple(MappingProxyType(dict(item)) for item in parameter_bindings_raw),
            )

        call_bindings: dict[tuple[str, str, str], TargetCallBinding] = {}
        call_keys: list[tuple[str, str, str]] = []
        call_fields = {
            "symbol_id",
            "overload_id",
            "call_form",
            "python_name",
            "parameters",
            "return_type",
            "state_model",
            "supported_pine_versions",
        }
        exact_call_fields = call_fields | {"python_module", "parameter_bindings"}
        delegated_call_fields = call_fields | {
            "disposition",
            "delegation_owner",
            "delegation_schema_id",
            "delegation_capability_id",
        }
        for index, raw in enumerate(call_bindings_raw):
            if not isinstance(raw, Mapping) or set(raw) not in {
                frozenset(call_fields),
                frozenset(exact_call_fields),
                frozenset(delegated_call_fields),
            }:
                raise BundleInvariantError(
                    "A2P_TARGET_CALL_BINDING",
                    "call binding fields are not exact",
                    path=f"$.call_bindings[{index}]",
                )
            string_fields = (
                "symbol_id",
                "overload_id",
                "call_form",
                "python_name",
                "return_type",
                "state_model",
            )
            if not all(isinstance(raw[field], str) and raw[field] for field in string_fields):
                raise BundleInvariantError(
                    "A2P_TARGET_CALL_BINDING", "call binding identities must be non-empty strings"
                )
            python_name = raw["python_name"]
            if not python_name.isidentifier() or keyword.iskeyword(python_name):
                raise BundleInvariantError("A2P_TARGET_PYTHON_NAME", "invalid call Python binding")
            parameters = raw["parameters"]
            versions = raw["supported_pine_versions"]
            if (
                not isinstance(parameters, list)
                or not all(isinstance(item, str) and item for item in parameters)
                or len(parameters) != len(set(parameters))
            ):
                raise BundleInvariantError(
                    "A2P_TARGET_CALL_PARAMETERS", "call parameters must be unique non-empty strings"
                )
            if (
                not isinstance(versions, list)
                or versions != sorted(set(versions))
                or not versions
                or not all(type(item) is int and item in range(1, 7) for item in versions)
            ):
                raise BundleInvariantError(
                    "A2P_TARGET_CALL_VERSIONS", "call versions must be sorted unique Pine versions"
                )
            python_module = raw.get("python_module")
            parameter_bindings_raw = raw.get("parameter_bindings", [])
            disposition = str(raw.get("disposition", "TARGET_DIRECT"))
            delegation_owner = raw.get("delegation_owner")
            delegation_schema_id = raw.get("delegation_schema_id")
            delegation_capability_id = raw.get("delegation_capability_id")
            if disposition == "TARGET_DELEGATED":
                if python_module is not None or parameter_bindings_raw:
                    raise BundleInvariantError(
                        "A2P_TARGET_DELEGATED_CALL",
                        "delegated call must not declare a direct callable",
                    )
                if not all(
                    isinstance(item, str) and item
                    for item in (
                        delegation_owner,
                        delegation_schema_id,
                        delegation_capability_id,
                    )
                ):
                    raise BundleInvariantError(
                        "A2P_TARGET_DELEGATED_CALL",
                        "delegated call identity is incomplete",
                    )
            elif disposition != "TARGET_DIRECT":
                raise BundleInvariantError(
                    "A2P_TARGET_CALL_BINDING",
                    "invalid call binding disposition",
                )
            if python_module is not None:
                if (
                    not isinstance(python_module, str)
                    or not python_module.startswith("pinelib.")
                    or not all(part.isidentifier() for part in python_module.split("."))
                ):
                    raise BundleInvariantError(
                        "A2P_TARGET_PINELIB_MODULE", "invalid exact PineLib module binding"
                    )
                if not isinstance(parameter_bindings_raw, list):
                    raise BundleInvariantError(
                        "A2P_TARGET_PARAMETER_BINDINGS",
                        "parameter bindings must be an array",
                    )
                for item in parameter_bindings_raw:
                    if (
                        not isinstance(item, Mapping)
                        or set(item) != {"abi_parameter", "binding", "source"}
                        or not isinstance(item.get("abi_parameter"), str)
                        or not item.get("abi_parameter")
                        or not isinstance(item.get("binding"), str)
                        or not item.get("binding")
                        or (
                            item.get("source") is None
                            and item.get("binding") not in {"ABI_DEFAULT", "UNBOUND_FAIL_CLOSED"}
                        )
                        or (
                            item.get("source") is not None
                            and not isinstance(item.get("source"), str)
                        )
                    ):
                        raise BundleInvariantError(
                            "A2P_TARGET_PARAMETER_BINDINGS",
                            "parameter binding fields are not exact strings",
                        )
            binding = TargetCallBinding(
                symbol_id=raw["symbol_id"],
                overload_id=raw["overload_id"],
                call_form=raw["call_form"],
                python_name=python_name,
                parameters=tuple(parameters),
                return_type=raw["return_type"],
                state_model=raw["state_model"],
                supported_pine_versions=tuple(versions),
                python_module=python_module,
                parameter_bindings=tuple(
                    MappingProxyType(dict(item)) for item in parameter_bindings_raw
                ),
                disposition=disposition,
                delegation_owner=delegation_owner,
                delegation_schema_id=delegation_schema_id,
                delegation_capability_id=delegation_capability_id,
            )
            if binding.key in call_bindings:
                raise BundleInvariantError(
                    "A2P_TARGET_CALL_BINDING", "duplicate exact call binding"
                )
            call_bindings[binding.key] = binding
            call_keys.append(binding.key)
        if call_keys != sorted(call_keys):
            raise BundleInvariantError("A2P_TARGET_CALL_BINDING", "call bindings must be sorted")

        value_bindings: dict[str, TargetValueBinding] = {}
        value_symbols: list[str] = []
        reference_value_fields = {"symbol_id", "python_name"}
        exact_value_fields = {
            "symbol_id",
            "disposition",
            "python_name",
            "python_module",
            "parameter_bindings",
            "return_type",
            "supported_pine_versions",
            "diagnostic",
        }
        delegated_value_fields = exact_value_fields | {
            "delegation_owner",
            "delegation_schema_id",
            "delegation_capability_id",
        }
        for index, raw in enumerate(value_bindings_raw):
            if not isinstance(raw, Mapping) or set(raw) not in {
                frozenset(reference_value_fields),
                frozenset(exact_value_fields),
                frozenset(delegated_value_fields),
            }:
                raise BundleInvariantError(
                    "A2P_TARGET_VALUE_BINDING",
                    "value binding fields are not exact",
                    path=f"$.value_bindings[{index}]",
                )
            symbol_id = raw["symbol_id"]
            python_name = raw["python_name"]
            if not isinstance(symbol_id, str) or not symbol_id:
                raise BundleInvariantError("A2P_TARGET_VALUE_BINDING", "invalid value binding")
            if set(raw) == reference_value_fields:
                if (
                    not isinstance(python_name, str)
                    or not python_name.isidentifier()
                    or keyword.iskeyword(python_name)
                ):
                    raise BundleInvariantError("A2P_TARGET_VALUE_BINDING", "invalid value binding")
                binding = TargetValueBinding(symbol_id, python_name)
            else:
                disposition = raw["disposition"]
                python_module = raw["python_module"]
                parameter_bindings_raw = raw["parameter_bindings"]
                return_type = raw["return_type"]
                versions = raw["supported_pine_versions"]
                diagnostic = raw["diagnostic"]
                if disposition not in {
                    "TARGET_DIRECT",
                    "TARGET_DELEGATED",
                    "UNSUPPORTED_FAIL_CLOSED",
                }:
                    raise BundleInvariantError(
                        "A2P_TARGET_VALUE_DISPOSITION", "invalid exact value disposition"
                    )
                if disposition == "TARGET_DIRECT" and (
                    not isinstance(python_name, str)
                    or not python_name.isidentifier()
                    or keyword.iskeyword(python_name)
                    or not isinstance(python_module, str)
                    or not python_module.startswith("pinelib.")
                    or not all(part.isidentifier() for part in python_module.split("."))
                ):
                    raise BundleInvariantError(
                        "A2P_TARGET_VALUE_CALLABLE", "invalid exact PineLib value callable"
                    )
                if disposition != "TARGET_DIRECT" and (
                    python_name is not None or python_module is not None
                ):
                    raise BundleInvariantError(
                        "A2P_TARGET_VALUE_CALLABLE",
                        "non-direct exact value must not declare a callable",
                    )
                delegation_owner = raw.get("delegation_owner")
                delegation_schema_id = raw.get("delegation_schema_id")
                delegation_capability_id = raw.get("delegation_capability_id")
                if disposition == "TARGET_DELEGATED" and not all(
                    isinstance(item, str) and item
                    for item in (
                        delegation_owner,
                        delegation_schema_id,
                        delegation_capability_id,
                    )
                ):
                    raise BundleInvariantError(
                        "A2P_TARGET_DELEGATED_VALUE",
                        "delegated value identity is incomplete",
                    )
                if not isinstance(parameter_bindings_raw, list):
                    raise BundleInvariantError(
                        "A2P_TARGET_VALUE_PARAMETERS", "value parameter bindings must be an array"
                    )
                for item in parameter_bindings_raw:
                    if (
                        not isinstance(item, Mapping)
                        or set(item) != {"abi_parameter", "binding", "source"}
                        or not isinstance(item.get("abi_parameter"), str)
                        or not item.get("abi_parameter")
                        or not isinstance(item.get("binding"), str)
                        or not item.get("binding")
                        or (
                            item.get("source") is not None
                            and not isinstance(item.get("source"), str)
                        )
                    ):
                        raise BundleInvariantError(
                            "A2P_TARGET_VALUE_PARAMETERS",
                            "value parameter binding fields are invalid",
                        )
                if not isinstance(return_type, str) or not return_type:
                    raise BundleInvariantError(
                        "A2P_TARGET_VALUE_RETURN", "exact value return type must be non-empty"
                    )
                if (
                    not isinstance(versions, list)
                    or versions != sorted(set(versions))
                    or not versions
                    or not all(type(item) is int and item in range(1, 7) for item in versions)
                ):
                    raise BundleInvariantError(
                        "A2P_TARGET_VALUE_VERSIONS", "invalid exact value versions"
                    )
                if diagnostic is not None and not isinstance(diagnostic, str):
                    raise BundleInvariantError(
                        "A2P_TARGET_VALUE_DIAGNOSTIC", "invalid exact value diagnostic"
                    )
                binding = TargetValueBinding(
                    symbol_id=symbol_id,
                    python_name=python_name,
                    disposition=disposition,
                    python_module=python_module,
                    parameter_bindings=tuple(
                        MappingProxyType(dict(item)) for item in parameter_bindings_raw
                    ),
                    return_type=return_type,
                    supported_pine_versions=tuple(versions),
                    diagnostic=diagnostic,
                    delegation_owner=delegation_owner,
                    delegation_schema_id=delegation_schema_id,
                    delegation_capability_id=delegation_capability_id,
                )
            if symbol_id in value_bindings:
                raise BundleInvariantError("A2P_TARGET_VALUE_BINDING", "duplicate value binding")
            value_bindings[symbol_id] = binding
            value_symbols.append(symbol_id)
        if value_symbols != sorted(value_symbols):
            raise BundleInvariantError("A2P_TARGET_VALUE_BINDING", "value bindings must be sorted")
        if not all(isinstance(item, str) and item for item in capabilities):
            raise BundleInvariantError("A2P_TARGET_CAPABILITIES", "capabilities must be strings")
        if capabilities != sorted(set(capabilities)):
            raise BundleInvariantError(
                "A2P_TARGET_CAPABILITIES",
                "capabilities must be sorted and unique",
            )
        if not all(isinstance(item, str) and item for item in allowed_imports):
            raise BundleInvariantError("A2P_TARGET_IMPORTS", "allowed imports must be strings")
        if allowed_imports != sorted(set(allowed_imports)):
            raise BundleInvariantError(
                "A2P_TARGET_IMPORTS",
                "allowed imports must be sorted and unique",
            )
        raw_body = {key: value[key] for key in value if key != "content_hash"}
        actual = "sha256:" + hashlib.sha256(canonical_json_bytes(raw_body)).hexdigest()
        if value["content_hash"] != actual:
            raise BundleInvariantError("A2P_TARGET_HASH", "target manifest content hash mismatch")
        manifest = cls(
            schema_id=value["schema_id"],
            schema_version=value["schema_version"],
            target_name=value["target_name"],
            target_version=value["target_version"],
            operations=MappingProxyType(operations),
            call_bindings=MappingProxyType(call_bindings),
            value_bindings=MappingProxyType(value_bindings),
            capabilities=frozenset(capabilities),
            allowed_imports=frozenset(allowed_imports),
            content_hash=actual,
            release_acceptance=value["release_acceptance"],
        )
        if canonical_json_bytes(manifest.to_body_dict()) != canonical_json_bytes(raw_body):
            raise BundleInvariantError(
                "A2P_TARGET_MATERIALIZATION",
                "materialized target manifest differs from its hashed body",
            )
        return manifest


def load_reference_target_manifest() -> TargetManifest:
    raw = json.loads(
        files("ast2python.target_data")
        .joinpath("reference_target_v1.json")
        .read_text(encoding="utf-8")
    )
    return TargetManifest.from_mapping(raw)
