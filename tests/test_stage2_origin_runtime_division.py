"""F2.2: mixed-import int division keeps origin policy at runtime.

Catalog: v5 const_int_division=TRUNCATE, v6 FRACTIONAL.
Producer facts: pine2ast tests/stage2/test_stage2_origin_preserving_division.py
and test_stage2_origin_param_division.py. This file is the emitted
runtime: v6 consumer + v5 library ``a / b`` must not apply v6.
"""

from __future__ import annotations

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)


def test_v6_consumer_v5_library_param_division_truncates() -> None:
    libs = {"user/Lib/1": library("export div(int a, int b)=>a/b", version=5)}
    compiled, linked = compile_linked(script("plot(lib.div(5, 2))", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [2]


def test_v6_same_version_library_param_division_is_fractional() -> None:
    libs = {"user/Lib/1": library("export div(int a, int b)=>a/b", version=6)}
    compiled, linked = compile_linked(script("plot(lib.div(5, 2))", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 6
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [2.5]


def test_v5_same_version_library_param_division_truncates() -> None:
    libs = {"user/Lib/1": library("export div(int a, int b)=>a/b", version=5)}
    compiled, linked = compile_linked(script("plot(lib.div(5, 2))", version=5), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [2]
