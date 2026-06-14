from __future__ import annotations

import sys

from ast2python.cli.commands import (
    command_coverage,
    command_lowering_matrix,
    command_smoke,
    command_source_map_contract,
    command_translate,
    command_translate_many,
    command_validate,
)
from ast2python.cli.parser import build_parser
from ast2python.errors import AST2PythonError


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
                compile_profile=args.compile_profile,
                strict=args.strict,
                emit_source_comments=not args.no_source_comments,
                allow_invalid_ast=args.allow_invalid_ast,
                allow_contract_mismatch=args.allow_contract_mismatch,
                allow_external_library_stubs=args.allow_external_library_stubs,
                allow_unsupported_request_stubs=args.allow_unsupported_request_stubs,
                allow_realtime_local_simulation=args.allow_realtime_local_simulation,
                visual_policy=args.visual_policy,
            )
        if args.command == "translate-many":
            return command_translate_many(
                args.ast_paths,
                args.output,
                compile_profile=args.compile_profile,
                strict=args.strict,
                emit_source_comments=not args.no_source_comments,
                allow_invalid_ast=args.allow_invalid_ast,
                allow_contract_mismatch=args.allow_contract_mismatch,
                allow_external_library_stubs=args.allow_external_library_stubs,
                allow_unsupported_request_stubs=args.allow_unsupported_request_stubs,
                allow_realtime_local_simulation=args.allow_realtime_local_simulation,
                visual_policy=args.visual_policy,
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


if __name__ == "__main__":
    raise SystemExit(main())
