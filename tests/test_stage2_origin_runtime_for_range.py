"""F2.3: mixed-import for-range keeps origin end evaluation at runtime.

Catalog: v5 for_range_end=FIXED, v6 DYNAMIC.
Same-script control: tests/test_stage2_language_execution.py
test_dynamic_end_is_only_reevaluated_in_v6
(v5 -> 2 iterations, v6 -> 3). Producer facts:
pine2ast tests/stage2/test_stage2_origin_for_range.py.
"""

from __future__ import annotations

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)

_BODY = (
    "export n()=>\n"
    "    int n=0\n"
    "    int bound=1\n"
    "    for i=0 to bound\n"
    "        n+=1\n"
    "        bound:=2\n"
    "    n\n"
)


def test_v6_consumer_v5_library_for_range_end_is_fixed() -> None:
    libs = {"user/Lib/1": library(_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.n())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [2]


def test_v6_same_version_library_for_range_end_is_dynamic() -> None:
    libs = {"user/Lib/1": library(_BODY, version=6)}
    compiled, linked = compile_linked(script("plot(lib.n())", version=6), libs)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [3]


def test_v5_same_version_library_for_range_end_is_fixed() -> None:
    libs = {"user/Lib/1": library(_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.n())", version=5), libs)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [2]
