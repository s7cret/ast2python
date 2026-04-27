from ast2python.diagnostics import SourceLocation
from ast2python.emitter import CodeEmitter
from ast2python.source_map import SourceMapBuilder


def test_code_emitter_tracks_source_map():
    source_map = SourceMapBuilder()
    emitter = CodeEmitter(source_map)
    emitter.line("x = 1", loc=SourceLocation(line=10, column=4), source="x = 1")
    emitter.line("y = 2")
    assert emitter.render() == "x = 1\ny = 2\n"
    assert source_map.to_list() == [
        {
            "python_line": 1,
            "pine_line": 10,
            "pine_column": 4,
            "pine_end_line": None,
            "pine_end_column": None,
            "pine_source": "x = 1",
        }
    ]
