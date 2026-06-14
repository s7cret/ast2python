from __future__ import annotations

import argparse


def _add_compile_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--compile-profile", choices=["production", "diagnostic"], default="production"
    )
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--no-source-comments", action="store_true")
    parser.add_argument("--allow-invalid-ast", action="store_true")
    parser.add_argument("--allow-contract-mismatch", action="store_true")
    parser.add_argument("--allow-external-library-stubs", action="store_true")
    parser.add_argument("--allow-unsupported-request-stubs", action="store_true")
    parser.add_argument("--allow-realtime-local-simulation", action="store_true")
    parser.add_argument(
        "--visual-policy",
        choices=["drop", "record", "error"],
        default="drop",
        help=(
            "visual-call lowering policy: drop/no-op for live trading, "
            "record to emit plot_recorder/debug output, or error to forbid visuals"
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ast2python")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("ast_path")

    translate_parser = subparsers.add_parser("translate")
    translate_parser.add_argument("ast_path")
    translate_parser.add_argument("-o", "--output", required=True)
    translate_parser.add_argument("--module-name")
    _add_compile_options(translate_parser)

    translate_many_parser = subparsers.add_parser("translate-many")
    translate_many_parser.add_argument("ast_paths", nargs="+")
    translate_many_parser.add_argument("-o", "--output", required=True)
    _add_compile_options(translate_many_parser)

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
