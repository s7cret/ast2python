from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

FORBIDDEN_PATH_PARTS = (
    "binder.py",
    "binder_model.py",
    "binder_registry.py",
    "binder_signatures/",
    "translate_api.py",
    "translator.py",
    "translator_mixins/",
    "translator_parts/",
    "runtime_contract/",
    "profiles.py",
)

FORBIDDEN = (
    "bind_builtin_call",
    "BUILTIN_SIGNATURES",
    "allow_invalid_ast",
    "allow_contract_mismatch",
    "allow_external_library_stubs",
    "allow_unsupported_request_stubs",
    "allow_realtime_local_simulation",
    "allow_implicit_version_rewrite",
    "allow_subprocess_fallback",
    "runtime_contract_v1_4",
    "semantic_profile",
    "TUPLE_RETURNING_BUILTINS",
    "PLAN_NODES =",
    "def _eval(",
    ".execute_operation(",
    ".execute_lazy_operation(",
)


def scan_tree(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative = path.relative_to(root).as_posix()
        if any(part in relative for part in FORBIDDEN_PATH_PARTS):
            findings.append({"path": relative, "symbol": "forbidden_path"})
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for symbol in FORBIDDEN:
            if symbol in text:
                findings.append({"path": relative, "symbol": symbol})
    return findings


def scan_wheel(path: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if not name.startswith("ast2python/"):
                continue
            if any(part in name for part in FORBIDDEN_PATH_PARTS):
                findings.append({"path": name, "symbol": "forbidden_path"})
            if not name.endswith((".py", ".json", ".md")):
                continue
            text = archive.read(name).decode("utf-8")
            for symbol in FORBIDDEN:
                if symbol in text:
                    findings.append({"path": name, "symbol": symbol})
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--wheel", type=Path)
    args = parser.parse_args()
    findings = scan_tree(args.source)
    if args.wheel:
        findings.extend(scan_wheel(args.wheel))
    print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
