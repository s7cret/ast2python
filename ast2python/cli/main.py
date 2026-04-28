from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import py_compile
import sys
from pathlib import Path
from typing import Any

from ast2python.ast.schema import load_ast, validate_ast
from ast2python.coverage import static_coverage_report
from ast2python.errors import AST2PythonError, UnsupportedNodeError
from ast2python.lowering_matrix import (
    LoweringMatrixError,
    export_lowering_matrix_markdown,
    export_source_map_contract_markdown,
    validate_lowering_matrix,
    validate_source_map_contract,
)
from ast2python.translator import Translator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ast2python")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("ast_path")

    translate_parser = subparsers.add_parser("translate")
    translate_parser.add_argument("ast_path")
    translate_parser.add_argument("-o", "--output", required=True)
    translate_parser.add_argument("--module-name")
    translate_parser.add_argument("--strict", action="store_true")
    translate_parser.add_argument("--no-source-comments", action="store_true")

    translate_many_parser = subparsers.add_parser("translate-many")
    translate_many_parser.add_argument("ast_paths", nargs="+")
    translate_many_parser.add_argument("-o", "--output", required=True)
    translate_many_parser.add_argument("--strict", action="store_true")
    translate_many_parser.add_argument("--no-source-comments", action="store_true")

    coverage_parser = subparsers.add_parser("coverage")
    coverage_parser.add_argument("ast_path")
    coverage_parser.add_argument("--strict", action="store_true")

    smoke_parser = subparsers.add_parser("smoke")
    smoke_parser.add_argument("python_path")
    smoke_parser.add_argument(
        "--bars", help="JSON or CSV bars file; defaults to two deterministic sample bars"
    )

    lowering_parser = subparsers.add_parser("lowering-matrix")
    lowering_parser.add_argument("action", choices=["validate", "export-md"])
    lowering_parser.add_argument("output", nargs="?", default="docs/LOWERING_MATRIX.md")

    source_map_parser = subparsers.add_parser("source-map-contract")
    source_map_parser.add_argument("action", choices=["validate", "export-md"])
    source_map_parser.add_argument("output", nargs="?", default="docs/SOURCE_MAP_CONTRACT.md")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return command_validate(args.ast_path)
        if args.command == "translate":
            return command_translate(
                args.ast_path,
                args.output,
                module_name=args.module_name,
                strict=args.strict,
                emit_source_comments=not args.no_source_comments,
            )
        if args.command == "translate-many":
            return command_translate_many(
                args.ast_paths,
                args.output,
                strict=args.strict,
                emit_source_comments=not args.no_source_comments,
            )
        if args.command == "coverage":
            return command_coverage(args.ast_path, strict=args.strict)
        if args.command == "smoke":
            return command_smoke(args.python_path, bars_path=args.bars)
        if args.command == "lowering-matrix":
            return command_lowering_matrix(args.action, output=args.output)
        if args.command == "source-map-contract":
            return command_source_map_contract(args.action, output=args.output)
    except AST2PythonError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def command_lowering_matrix(action: str, *, output: str) -> int:
    try:
        if action == "validate":
            validate_lowering_matrix()
            print("OK lowering matrix")
        elif action == "export-md":
            validate_lowering_matrix()
            print(export_lowering_matrix_markdown(output))
    except LoweringMatrixError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def command_source_map_contract(action: str, *, output: str) -> int:
    try:
        if action == "validate":
            validate_source_map_contract()
            print("OK source-map contract")
        elif action == "export-md":
            validate_source_map_contract()
            print(export_source_map_contract_markdown(output))
    except LoweringMatrixError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def command_validate(ast_path: str) -> int:
    program = load_ast(ast_path)
    problems = validate_ast(program)
    static = static_coverage_report(program)
    payload = {
        "ok": not problems,
        "problems": problems,
        "nodes_total": static["nodes_total"],
        "unsupported_nodes": static["unsupported_nodes"],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not problems else 1


def command_translate(
    ast_path: str,
    output: str,
    *,
    module_name: str | None,
    strict: bool,
    emit_source_comments: bool,
) -> int:
    translator = Translator(strict=strict, emit_source_comments=emit_source_comments)
    result = translator.translate_file(ast_path, module_name=module_name)
    paths = result.write_to(output)
    print(
        json.dumps(
            {
                "module": result.module_name,
                "paths": {key: str(value) for key, value in paths.items()},
                "diagnostics": [diagnostic.to_dict() for diagnostic in result.diagnostics],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 1 if any(item.severity.value == "error" for item in result.diagnostics) else 0


def command_translate_many(
    ast_paths: list[str],
    output: str,
    *,
    strict: bool,
    emit_source_comments: bool,
) -> int:
    output_dir = Path(output)
    modules: list[dict[str, Any]] = []
    has_error = False
    for ast_path in ast_paths:
        translator = Translator(strict=strict, emit_source_comments=emit_source_comments)
        result = translator.translate_file(ast_path, module_name=Path(ast_path).stem)
        paths = result.write_to(output_dir)
        diagnostics = [diagnostic.to_dict() for diagnostic in result.diagnostics]
        has_error = has_error or any(
            diagnostic.severity.value == "error" for diagnostic in result.diagnostics
        )
        modules.append(
            {
                "input": ast_path,
                "module": result.module_name,
                "paths": {key: str(value) for key, value in paths.items()},
                "diagnostics": diagnostics,
                "coverage": result.coverage,
            }
        )
    print(json.dumps({"ok": not has_error, "modules": modules}, indent=2, sort_keys=True))
    return 1 if has_error else 0


def command_coverage(ast_path: str, *, strict: bool) -> int:
    program = load_ast(ast_path)
    static = static_coverage_report(program)
    try:
        translator = Translator(strict=strict)
        result = translator.translate_program(program, module_name=Path(ast_path).stem)
        payload = {
            **static,
            **result.coverage,
            "diagnostics": [item.to_dict() for item in result.diagnostics],
        }
        status = 0
    except UnsupportedNodeError as exc:
        payload = {**static, "ok": False, "error": str(exc)}
        status = 1 if strict else 0
    print(json.dumps(payload, indent=2, sort_keys=True))
    return status


def _ensure_local_pinelib_importable() -> bool:
    try:
        import pinelib  # noqa: F401

        return True
    except ModuleNotFoundError:
        local = Path("[local-home]/pinelib")
        if local.exists():
            sys.path.insert(0, str(local))
            try:
                import pinelib  # noqa: F401

                return True
            except ModuleNotFoundError:
                return False
        return False


def _load_bars(path: str | None) -> list[Any]:
    from pinelib.core import Bar

    if path is None:
        return [
            Bar(
                time=1704067200000,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=10.0,
                time_close=1704067259999,
            ),
            Bar(
                time=1704067260000,
                open=100.5,
                high=102.0,
                low=100.0,
                close=101.5,
                volume=12.0,
                time_close=1704067319999,
            ),
        ]
    bars_path = Path(path)
    if bars_path.suffix.lower() == ".json":
        raw = json.loads(bars_path.read_text(encoding="utf-8"))
        return [Bar(**item) for item in raw]
    with bars_path.open(newline="", encoding="utf-8") as fh:
        rows = csv.DictReader(fh)
        return [
            Bar(
                time=int(row["time"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume") or 0.0),
                time_close=int(row["time_close"]) if row.get("time_close") else None,
            )
            for row in rows
        ]


def _load_generated_class(python_path: Path) -> type[Any]:
    spec = importlib.util.spec_from_file_location(python_path.stem, python_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import generated module {python_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[python_path.stem] = module
    spec.loader.exec_module(module)
    for name in ("GeneratedStrategy", "GeneratedIndicator", "GeneratedLibrary", "GeneratedScript"):
        klass = getattr(module, name, None)
        if isinstance(klass, type):
            return klass
    raise RuntimeError("generated module does not expose a Generated* class")


def command_smoke(python_path: str, *, bars_path: str | None = None) -> int:
    path = Path(python_path)
    py_compile.compile(str(path), doraise=True)
    if not _ensure_local_pinelib_importable():
        print(
            json.dumps(
                {
                    "ok": True,
                    "python_path": str(path),
                    "runtime": "skipped",
                    "reason": "pinelib not importable",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    from pinelib.core import PineRuntime, SymbolInfo, TimeframeInfo

    bars = _load_bars(bars_path)
    klass = _load_generated_class(path)
    runtime = PineRuntime(
        symbol_info=SymbolInfo(tickerid="TEST", timezone="UTC"),
        timeframe=TimeframeInfo.from_string("1"),
    )
    for name in ("plot", "plotshape", "plotchar", "hline", "fill", "bgcolor", "barcolor"):
        if not hasattr(runtime.visual, name):
            setattr(runtime.visual, name, lambda *args, **kwargs: None)
    instance = klass(params={}, runtime=runtime)
    snapshots = instance.run(bars)
    print(
        json.dumps(
            {
                "ok": True,
                "python_path": str(path),
                "runtime": "executed",
                "bars": len(bars),
                "snapshots": len(snapshots),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
