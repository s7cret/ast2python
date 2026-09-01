from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ast2python.distribution import build_distribution_manifest
from ast2python.version import (
    CONSUMER_BUNDLE_SCHEMA_ID,
    CONSUMER_BUNDLE_SCHEMA_VERSION,
    REQUIRED_PINE2AST_VERSION,
    __version__,
)

_RELEASE_SCHEMA = "ast2python.rc6.pass3.release_report.v1"
_REQUIRED_PUBLIC_API = frozenset(
    {
        "validate_consumer_bundle",
        "admit_consumer_bundle",
        "inspect_consumer_bundle",
        "open_compilation_session",
        "compile_consumer_bundle",
        "write_compilation_result",
        "verify_generated_artifact_v3",
        "load_reference_target_manifest",
    }
)
_REMOVED_MODULES = (
    "arg_helper.py",
    "artifact.py",
    "ast",
    "binder.py",
    "binder_model.py",
    "binder_registry.py",
    "binder_signatures",
    "call_dispatch.py",
    "call_handler_types.py",
    "call_handlers.py",
    "call_handlers_builtin.py",
    "call_handlers_common.py",
    "call_handlers_request.py",
    "call_handlers_strategy.py",
    "call_handlers_time.py",
    "call_registry.py",
    "context.py",
    "coverage.py",
    "diagnostics.py",
    "emitter.py",
    "emitters",
    "imports.py",
    "lowering_matrix",
    "naming.py",
    "openpine_compat.py",
    "profiles.py",
    "result.py",
    "runtime_contract",
    "scheduler.py",
    "source_map.py",
    "state.py",
    "switch_helper.py",
    "templates",
    "translate_api.py",
    "translator.py",
    "translator_constants.py",
    "translator_mixins",
    "translator_parts",
    "translator_protocols.py",
    "translator_support.py",
    "types.py",
    "unsupported.py",
    "visuals.py",
)
_REQUIRED_STAGE4_MODULES = (
    "compiler.py",
    "lowering/model.py",
    "lowering/builder.py",
    "lowering/validate.py",
    "lowering/target.py",
    "emission/python.py",
    "emission/source_map.py",
    "artifacts/generated.py",
    "hardening/mutations.py",
    "hardening/fuzz.py",
    "hardening/differential.py",
    "hardening/security.py",
)


@dataclass(frozen=True, slots=True)
class ReleaseFinding:
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True, slots=True)
class ReleaseReport:
    root: str
    findings: tuple[ReleaseFinding, ...]
    distribution: dict[str, Any]

    @property
    def ok(self) -> bool:
        """Implementation/package readiness, not authorization to merge or release."""
        return not self.findings and bool(self.distribution.get("ok"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": _RELEASE_SCHEMA,
            "ok": self.ok,
            "package_version": __version__,
            "consumer_contract": {
                "schema_id": CONSUMER_BUNDLE_SCHEMA_ID,
                "schema_version": CONSUMER_BUNDLE_SCHEMA_VERSION,
                "required_pine2ast_version": REQUIRED_PINE2AST_VERSION,
            },
            "stage": "near-final-pass3",
            "runnable_output_available": True,
            "compiler_architecture": {
                "production_input": "pine2ast.consumer_bundle.v1",
                "typed_ir": "ast2python.lowering_plan.v1",
                "source_map": "openpine.source_map.v2",
                "generated_artifact": "openpine.generated_artifact.v3",
                "raw_ast_api": False,
                "local_semantic_rebinding": False,
                "stub_lowering": False,
            },
            "release_acceptance": {
                "pine2ast_rc6": "EXACT_CORRECTED_BUNDLES_ACCEPTED",
                "pinelib_rc6": "EXTERNAL_EXACT_TARGET_EVIDENCE_REQUIRED",
                "python_3_11": "EXTERNAL_GATE_REQUIRED",
                "python_3_12": "EXTERNAL_GATE_REQUIRED",
                "python_3_13": "LOCAL_GATE_AVAILABLE",
                "rc5_rc6_differential": "EXTERNAL_EXACT_RC5_ARTIFACT_REQUIRED",
                "hosted_ci": "NOT_RUN_FROM_LOCAL_PACKET",
            },
            "authorization": {
                "merge": False,
                "release": False,
                "deployment": False,
            },
            "root": self.root,
            "distribution": self.distribution,
            "findings": [item.to_dict() for item in self.findings],
        }


def build_release_report(root: str | Path = ".") -> ReleaseReport:
    root_path = Path(root).resolve()
    package_root = root_path / "ast2python"
    findings: list[ReleaseFinding] = []
    distribution = build_distribution_manifest(root_path).to_dict()
    if __version__ != "5.0.0rc6":
        findings.append(ReleaseFinding("wrong_version", "ast2python/version.py", __version__))
    pyproject = root_path / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8")
        if 'version = "5.0.0rc6"' not in text:
            findings.append(
                ReleaseFinding("pyproject_version", "pyproject.toml", "version mismatch")
            )
        if '"pine2ast==5.0.0rc6"' not in text:
            findings.append(
                ReleaseFinding("dependency_pin", "pyproject.toml", "exact Pine2AST RC6 pin missing")
            )
    else:
        findings.append(ReleaseFinding("missing_pyproject", "pyproject.toml", "file missing"))
    init_path = package_root / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8") if init_path.is_file() else ""
    for symbol in sorted(_REQUIRED_PUBLIC_API):
        if re.search(rf'"{re.escape(symbol)}"', init_text) is None:
            findings.append(ReleaseFinding("public_api_missing", "ast2python/__init__.py", symbol))
    for symbol in (
        "OPENPINE_RC5_COMPILER_COMPAT",
        "install_rc5_profiles_alias",
        "translate_ast",
    ):
        if symbol in init_text:
            findings.append(
                ReleaseFinding(
                    "legacy_surface_present",
                    "ast2python/__init__.py",
                    symbol,
                )
            )
    for relative in _REMOVED_MODULES:
        if (package_root / relative).exists():
            findings.append(
                ReleaseFinding("legacy_module_present", f"ast2python/{relative}", "must be removed")
            )
    for relative in _REQUIRED_STAGE4_MODULES:
        if not (package_root / relative).is_file():
            findings.append(
                ReleaseFinding(
                    "stage4_module_missing",
                    f"ast2python/{relative}",
                    "required Stage 4 module missing",
                )
            )
    if not (package_root / "py.typed").is_file():
        findings.append(
            ReleaseFinding(
                "py_typed_missing", "ast2python/py.typed", "typed package marker missing"
            )
        )
    return ReleaseReport(root=str(root_path), findings=tuple(findings), distribution=distribution)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ast2python.release")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    report = build_release_report(args.root)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
