"""F2.5: mixed-import written callsites stay independent at runtime.

Same-version control: tests/test_locked_library_execution.py
test_independent_written_imported_calls_and_local_var_restore.
This file is v6 consumer + v5 library: two written ``lib.count`` calls
must not share var state after linking/projection.
"""

from __future__ import annotations

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)


def test_v6_consumer_v5_library_two_written_calls_are_independent() -> None:
    libs = {
        "user/Lib/1": library(
            "export count(int step=1)=>\n    var int n=0\n    n+=step\n    n",
            version=5,
        )
    }
    compiled, linked = compile_linked(
        script("plot(lib.count())\nplot(lib.count(step=10))", version=6),
        libs,
    )
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    assert "//@version=5" in linked.receipt()["sources"]["user/Lib/1"]["raw_text"]
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1, 2, 3]) == [1, 10, 2, 20, 3, 30]
