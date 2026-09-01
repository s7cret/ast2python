from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ast2python")
    parser.add_argument("--version", action="store_true", help="print package version")
    subparsers = parser.add_subparsers(dest="command")

    validate = subparsers.add_parser("validate-bundle", help="validate a Pine2AST consumer bundle")
    validate.add_argument("path")
    validate.add_argument("--analysis", action="store_true")
    validate.add_argument("--json", action="store_true", dest="as_json")

    inspect = subparsers.add_parser("inspect-bundle", help="inspect an admitted bundle")
    inspect.add_argument("path")
    inspect.add_argument("--json", action="store_true", dest="as_json")

    compile_cmd = subparsers.add_parser(
        "compile-bundle", help="compile an exact Pine2AST consumer bundle"
    )
    compile_cmd.add_argument("path")
    compile_cmd.add_argument("--output", required=True)
    compile_cmd.add_argument("--target-manifest", required=True)
    compile_cmd.add_argument("--module-name", default="generated_pine_script")
    compile_cmd.add_argument("--json", action="store_true", dest="as_json")
    return parser
