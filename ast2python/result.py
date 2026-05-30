from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ast2python.diagnostics import Diagnostic


@dataclass
class TranslationResult:
    code: str
    metadata: dict[str, Any]
    source_map: list[dict[str, Any]]
    coverage: dict[str, Any]
    diagnostics: list[Diagnostic]
    module_name: str

    def write_to(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        py_path = output / f"{self.module_name}.py"
        meta_path = output / f"{self.module_name}.meta.json"
        sourcemap_path = output / f"{self.module_name}.sourcemap.json"
        coverage_path = output / f"{self.module_name}.coverage.json"
        py_path.write_text(self.code, encoding="utf-8")
        meta_path.write_text(
            json.dumps(self.metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        sourcemap_path.write_text(
            json.dumps(self.source_map, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        coverage_path.write_text(
            json.dumps(self.coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return {
            "python": py_path,
            "metadata": meta_path,
            "source_map": sourcemap_path,
            "coverage": coverage_path,
        }
