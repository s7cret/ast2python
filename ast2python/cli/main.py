from __future__ import annotations

from ast2python.cli.commands import run_compile, run_inspect, run_validate
from ast2python.cli.parser import build_parser
from ast2python.version import __version__


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    if args.command == "validate-bundle":
        return run_validate(args.path, analysis=args.analysis, as_json=args.as_json)
    if args.command == "inspect-bundle":
        return run_inspect(args.path, as_json=args.as_json)
    if args.command == "compile-bundle":
        return run_compile(
            args.path,
            output=args.output,
            module_name=args.module_name,
            target_manifest=args.target_manifest,
            as_json=args.as_json,
        )
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
