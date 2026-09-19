"""F2.3: mixed-import and/or keep origin eager/lazy evaluation at runtime.

Catalog: v5 logical_evaluation=EAGER, v6 LAZY.
Same-script control: tests/test_stage2_language_execution.py
test_short_circuit_respects_version_instead_of_always_python_lazy.
"""

from __future__ import annotations

import pytest
from pinelib.errors import PineRuntimeError

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)

_BODY = "export f()=>\n    a=false and (1/(close-close)>0)\n    a ? 1 : 0\n"


def test_v6_consumer_v5_library_and_is_eager() -> None:
    libs = {"user/Lib/1": library(_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.f())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    with pytest.raises(PineRuntimeError, match="division by zero"):
        advance(runtime, cls, [1])


def test_v6_same_version_library_and_is_lazy() -> None:
    libs = {"user/Lib/1": library(_BODY, version=6)}
    compiled, linked = compile_linked(script("plot(lib.f())", version=6), libs)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v5_same_version_library_and_is_eager() -> None:
    libs = {"user/Lib/1": library(_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.f())", version=5), libs)
    runtime, cls = runtime_for(compiled)
    with pytest.raises(PineRuntimeError, match="division by zero"):
        advance(runtime, cls, [1])
