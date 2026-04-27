from __future__ import annotations

CLASS_BY_MODE = {
    "strategy": "GeneratedStrategy",
    "indicator": "GeneratedIndicator",
    "library": "GeneratedLibrary",
}

BASE_BY_MODE = {
    "strategy": "GeneratedStrategyBase",
    "indicator": "GeneratedIndicatorBase",
    "library": "GeneratedLibraryBase",
}


def class_name_for_mode(mode: str) -> str:
    return CLASS_BY_MODE.get(mode, "GeneratedScript")


def base_class_for_mode(mode: str) -> str:
    return BASE_BY_MODE.get(mode, "GeneratedScriptBase")
