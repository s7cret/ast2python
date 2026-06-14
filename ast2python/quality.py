from __future__ import annotations

import argparse
import ast
import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

IGNORED_DIRS = {
    "__pycache__",
    ".git",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".venv",
    "venv",
    "htmlcov",
}


@dataclass(frozen=True)
class ArchitectureReport:
    max_lines: int
    oversized_count: int
    oversized: list[dict[str, int | str]]


@dataclass(frozen=True)
class DuplicateReport:
    duplicate_group_count: int
    groups: list[dict[str, object]]


def _python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        yield path


def architecture_report(root: str | Path, *, max_lines: int = 700) -> ArchitectureReport:
    root_path = Path(root)
    oversized: list[dict[str, int | str]] = []
    for path in _python_files(root_path):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > max_lines:
            oversized.append({"path": str(path), "lines": line_count})
    oversized.sort(key=lambda item: (-int(item["lines"]), str(item["path"])))
    return ArchitectureReport(
        max_lines=max_lines, oversized_count=len(oversized), oversized=oversized
    )


def _normalised_function_body(node: ast.AST) -> str | None:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    if node.name == "__init__":
        return None
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if not body:
        return None
    if len(body) == 1:
        only = body[0]
        if isinstance(only, ast.Pass):
            return None
        if (
            isinstance(only, ast.Expr)
            and isinstance(only.value, ast.Constant)
            and only.value.value is Ellipsis
        ):
            return None
        if isinstance(only, ast.Raise):
            return None
    dumped = ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)
    if len(dumped) < 90:
        return None
    return dumped


def duplicate_report(root: str | Path) -> DuplicateReport:
    root_path = Path(root)
    buckets: dict[str, list[str]] = {}
    for path in _python_files(root_path):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            body = _normalised_function_body(node)
            if body is None:
                continue
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
            name = getattr(node, "name", "<anonymous>")
            buckets.setdefault(digest, []).append(f"{path}:{name}")
    groups: list[dict[str, object]] = [
        {"digest": digest, "locations": sorted(locations)}
        for digest, locations in buckets.items()
        if len(locations) > 1
    ]
    groups.sort(key=lambda item: str(item["digest"]))
    return DuplicateReport(duplicate_group_count=len(groups), groups=groups)


def _print_report(report: ArchitectureReport | DuplicateReport) -> None:
    print(json.dumps(asdict(report), indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ast2python.quality")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dup = subparsers.add_parser("duplicates")
    dup.add_argument("root")
    arch = subparsers.add_parser("architecture")
    arch.add_argument("root")
    arch.add_argument("--max-lines", type=int, default=700)
    args = parser.parse_args(argv)
    if args.command == "duplicates":
        duplicate = duplicate_report(args.root)
        _print_report(duplicate)
        return 1 if duplicate.duplicate_group_count else 0
    if args.command == "architecture":
        architecture = architecture_report(args.root, max_lines=args.max_lines)
        _print_report(architecture)
        return 1 if architecture.oversized_count else 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
