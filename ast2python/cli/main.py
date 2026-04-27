from __future__ import annotations

import argparse
import json
import py_compile
import sys
from pathlib import Path

from ast2python.ast.schema import load_ast, validate_ast
from ast2python.errors import AST2PythonError
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

    coverage_parser = subparsers.add_parser("coverage")
    coverage_parser.add_argument("ast_path")
    coverage_parser.add_argument("--strict", action="store_true")

    smoke_parser = subparsers.add_parser("smoke")
    smoke_parser.add_argument("python_path")
    smoke_parser.add_argument("--bars")

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
        if args.command == "coverage":
            return command_coverage(args.ast_path, strict=args.strict)
        if args.command == "smoke":
            return command_smoke(args.python_path)
    except AST2PythonError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def command_validate(ast_path: str) -> int:
    program = load_ast(ast_path)
    problems = validate_ast(program)
    payload = {
        "ok": not problems,
        "problems": problems,
        "nodes_total": sum(1 for _ in program.descendants()),
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


def command_coverage(ast_path: str, *, strict: bool) -> int:
    translator = Translator(strict=strict)
    result = translator.translate_file(ast_path)
    print(json.dumps(result.coverage, indent=2, sort_keys=True))
    return 0


def command_smoke(python_path: str) -> int:
    py_compile.compile(str(Path(python_path)), doraise=True)
    print(json.dumps({"ok": True, "python_path": str(Path(python_path))}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
