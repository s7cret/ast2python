from __future__ import annotations

import ast
import copy
import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ast2python import (
    compile_consumer_bundle as compile_production_bundle,
)
from ast2python import (
    compile_reference_consumer_bundle as compile_consumer_bundle,
)
from ast2python import (
    load_reference_target_manifest,
)
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.artifacts import verify_generated_artifact_v3
from ast2python.emission import emit_python_module, verify_source_map_v2
from ast2python.errors import BundleInvariantError
from ast2python.lowering import TargetManifest, validate_lowering_plan
from ast2python.lowering.validate import verify_lowering_plan_payload


@dataclass(frozen=True, slots=True)
class FuzzReport:
    seed: int
    requested_cases: int
    executed_cases: int
    failures: tuple[dict[str, Any], ...]
    transcript_hash: str
    shape_counts: dict[str, int]
    versions_seen: tuple[int, ...]

    @property
    def ok(self) -> bool:
        return self.executed_cases == self.requested_cases and not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "ast2python.stage4.fuzz.v1",
            "ok": self.ok,
            "seed": self.seed,
            "requested_cases": self.requested_cases,
            "executed_cases": self.executed_cases,
            "failure_count": len(self.failures),
            "failures": list(self.failures),
            "transcript_hash": self.transcript_hash,
            "shape_counts": dict(sorted(self.shape_counts.items())),
            "versions_seen": list(self.versions_seen),
        }


class _ReferenceRuntime:
    def __init__(self, target: Any) -> None:
        self.target_manifest_hash = target.content_hash
        self.supported_operations = frozenset(target.operations)
        self.capabilities = target.capabilities
        self.calls = 0

    def __getattr__(self, name: str) -> Any:
        if name.startswith("value_"):
            return 1.0
        if name.startswith("call_"):

            def invoke(*args: Any, **kwargs: Any) -> Any:
                self.calls += 1
                return args[-1] if args else None

            return invoke
        if name.startswith("op_"):

            def operation(*args: Any) -> Any:
                if "operator_binary" in name and len(args) == 3:
                    operator, left, right = args
                    return {
                        "+": left + right,
                        "-": left - right,
                        "*": left * right,
                        "/": None if right == 0 else left / right,
                        ">": left > right,
                        ">=": left >= right,
                        "<": left < right,
                        "<=": left <= right,
                        "==": left == right,
                        "!=": left != right,
                    }[operator]
                return args[-1] if args else None

            return operation
        raise AttributeError(name)


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(value)
    value.pop("content_hash", None)
    value["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    return value


def run_deterministic_fuzz(
    bundle_paths: Sequence[str | Path],
    *,
    cases: int = 10_000,
    seed: int = 0xA2F40004,
) -> FuzzReport:
    if cases < 1:
        raise BundleInvariantError("A2P_FUZZ_CASES", "fuzz cases must be positive")
    target = load_reference_target_manifest()
    inputs = [Path(path) for path in bundle_paths]
    if not inputs:
        raise BundleInvariantError("A2P_FUZZ_INPUTS", "fuzz requires at least one bundle")
    compiled = [
        (path, compile_consumer_bundle(path, module_name=f"fuzz_v{index + 1}"))
        for index, path in enumerate(inputs)
    ]
    rng = random.Random(seed)
    failures: list[dict[str, Any]] = []
    transcript: list[str] = []
    shapes: dict[str, int] = {}
    versions_seen: set[int] = set()
    shape_options = (
        "plan",
        "artifact",
        "source_map",
        "emit",
        "runtime",
        "unsafe_name",
        "invalid_plan_hash",
        "invalid_artifact_hash",
        "target_subset",
    )
    for case_index in range(cases):
        path, result = compiled[rng.randrange(len(compiled))]
        versions_seen.add(result.plan.pine_version)
        shape = rng.choice(shape_options)
        shapes[shape] = shapes.get(shape, 0) + 1
        try:
            if shape == "plan":
                validate_lowering_plan(result.plan, target)
                token = result.plan.content_hash
            elif shape == "artifact":
                verify_generated_artifact_v3(
                    result.artifact.payload,
                    plan=result.plan,
                    target=target,
                    emitted=result.emitted,
                )
                token = str(result.artifact.payload["content_hash"])
            elif shape == "source_map":
                verify_source_map_v2(
                    result.emitted.source_map.to_dict(),
                    expected_ir_ids=set(result.plan.nodes),
                )
                token = result.emitted.source_map.content_hash
            elif shape == "emit":
                name = f"generated_{case_index}_{rng.randrange(1_000_000)}"
                emitted = emit_python_module(result.plan, target, module_name=name)
                ast.parse(emitted.code)
                token = emitted.code_hash
            elif shape == "runtime":
                namespace: dict[str, Any] = {}
                exec(compile(result.emitted.code, "<fuzz-generated>", "exec"), namespace)
                runtime = _ReferenceRuntime(target)
                namespace["GeneratedScript"](runtime).run()
                if "self.runtime.call_" in result.emitted.code and runtime.calls <= 0:
                    raise AssertionError("direct runtime did not receive any bound call")
                token = str(runtime.calls)
            elif shape == "unsafe_name":
                unsafe = rng.choice(
                    ("bad-name", "x;import os", "../x", "x y", "1bad", "x\nexec('1')")
                )
                try:
                    emit_python_module(result.plan, target, module_name=unsafe)
                except BundleInvariantError:
                    token = "rejected"
                else:
                    raise AssertionError("unsafe module name was accepted")
            elif shape == "invalid_plan_hash":
                payload = result.plan.to_dict()
                payload["content_hash"] = "sha256:" + "0" * 64
                try:
                    verify_lowering_plan_payload(payload, target=target)
                except BundleInvariantError:
                    token = "rejected"
                else:
                    raise AssertionError("invalid lowering plan hash was accepted")
            elif shape == "invalid_artifact_hash":
                payload = dict(result.artifact.payload)
                payload["content_hash"] = "sha256:" + "0" * 64
                try:
                    verify_generated_artifact_v3(payload)
                except BundleInvariantError:
                    token = "rejected"
                else:
                    raise AssertionError("invalid artifact hash was accepted")
            else:
                target_payload = target.to_dict()
                required = sorted(result.plan.required_operations)
                removed = rng.choice(required)
                target_payload["operations"] = [
                    row for row in target_payload["operations"] if row["name"] != removed
                ]
                reduced = TargetManifest.from_mapping(_seal(target_payload))
                try:
                    compile_production_bundle(path, target=reduced)
                except BundleInvariantError:
                    token = f"rejected:{removed}"
                else:
                    raise AssertionError("target missing a required operation was accepted")
            transcript.append(
                f"{case_index}:{shape}:v{result.plan.pine_version}:{result.plan.bundle_hash}:{token}"
            )
        except Exception as exc:  # recorded as a fuzz failure, never treated as success
            failures.append(
                {
                    "case": case_index,
                    "shape": shape,
                    "pine_version": result.plan.pine_version,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            transcript.append(f"{case_index}:{shape}:FAIL:{type(exc).__name__}")
    transcript_hash = "sha256:" + hashlib.sha256("\n".join(transcript).encode("utf-8")).hexdigest()
    return FuzzReport(
        seed,
        cases,
        cases,
        tuple(failures),
        transcript_hash,
        shapes,
        tuple(sorted(versions_seen)),
    )
