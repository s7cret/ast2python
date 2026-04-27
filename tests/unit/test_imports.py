from ast2python.imports import ImportManager


def test_import_manager_conflict_aliases():
    manager = ImportManager()
    assert manager.require_from("pinelib.math", "round") == "pine_round"
    assert manager.require_from("pinelib.math", "abs") == "pine_abs"
    lines = manager.render()
    assert "from pinelib.math import abs as pine_abs, round as pine_round" in lines
