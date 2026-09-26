"""F2.3: mixed-import bool NA keeps origin condition policy at runtime.

Catalog authority is pine2ast catalog_source/version_rules.json:
v5 bool_allows_na=true, v6 bool_allows_na=false.
Producer admission: tests/stage2/test_stage2_origin_bool_na.py.
Same-script control in this file: v5 ``bool x = na; x ? 1 : 0`` is 0,
because a v5 condition treats na bool as false. The mixed case must
match that control, not the v6 session rule that rejects na bool.
"""

from __future__ import annotations

from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib import is_na

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)

_BODY = "export flag() =>\n    bool x = na\n    x ? 1 : 0\n"
_IF_BODY = "export flag() =>\n    bool x = na\n    if x\n        1\n    else\n        0\n"
_WHILE_BODY = (
    "export flag() =>\n    bool x = na\n    int n = 0\n    while x\n        n += 1\n    n\n"
)
_HISTORY_BODY = "export prev() =>\n    bool x = true\n    x[1]\n"
_NA_BODY = "export flag() =>\n    na(true)\n"
_AND_BODY = "export flag() =>\n    bool x = na\n    x and false ? 1 : 0\n"
_NUMERIC_AND_BODY = "export flag() =>\n    1 and 0 ? 1 : 0\n"
_NZ_BODY = "export flag() =>\n    nz(true) ? 1 : 0\n"
_BOOL_CAST_BODY = "export flag() =>\n    na(bool(na)) ? 1 : 0\n"


def test_v5_same_version_library_na_bool_condition_is_false() -> None:
    libs = {"user/Lib/1": library(_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=5), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v6_consumer_v5_library_na_bool_condition_is_false() -> None:
    libs = {"user/Lib/1": library(_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    assert "//@version=5" in linked.receipt()["sources"]["user/Lib/1"]["raw_text"]
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v5_same_version_library_if_na_bool_is_false() -> None:
    libs = {"user/Lib/1": library(_IF_BODY, version=5)}
    compiled, _linked = compile_linked(script("plot(lib.flag())", version=5), libs)
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v6_consumer_v5_library_if_na_bool_is_false() -> None:
    libs = {"user/Lib/1": library(_IF_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v6_consumer_v5_library_while_na_bool_does_not_run() -> None:
    libs = {"user/Lib/1": library(_WHILE_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v6_same_version_library_na_bool_is_not_executable() -> None:
    libs = {"user/Lib/1": library(_BODY, version=6)}
    try:
        compile_linked(script("plot(lib.flag())", version=6), libs)
    except (ConsumerBundleError, Exception) as exc:
        assert (
            "BOOL" in type(exc).__name__
            or "bool" in str(exc).lower()
            or isinstance(exc, ConsumerBundleError)
        )
        return
    raise AssertionError("v6 library bool na must not compile")


def test_v6_consumer_v5_library_missing_bool_history_is_na() -> None:
    """v5 missing bool history is na, not the v6 session False.

    Authority: pinelib tests/test_versioned_bool_history.py, which is the
    same flip as catalog bool_allows_na (false only in v6).
    """
    libs = {"user/Lib/1": library(_HISTORY_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.prev())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert is_na(advance(runtime, cls, [1])[0])


def test_v6_consumer_v5_library_na_accepts_bool() -> None:
    """v5 na(bool) is legal. A v6 session must not reject the library call."""

    libs = {"user/Lib/1": library(_NA_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v6_consumer_v5_library_and_na_bool_is_false() -> None:
    """v5 `and` must treat na bool as false, not the v6 session rejection."""

    libs = {"user/Lib/1": library(_AND_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v6_consumer_v5_library_numeric_and_is_false() -> None:
    """v5 `1 and 0` is false. A v6 session must not reject the numeric operand.

    Catalog: v5 numeric_condition_allowed=true, v6 false.
    Producer admission is tests/stage2/test_stage2_origin_logical_numeric.py.
    Expected 0 is the v5 truthiness of 0, not a value copied from this run.
    """

    libs = {"user/Lib/1": library(_NUMERIC_AND_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [0]


def test_v6_consumer_v5_library_nz_accepts_bool() -> None:
    """v5 nz(bool) is legal and keeps the value. A v6 session must not reject it.

    Authority: pinelib pine_nz allows bool only when pine_version <= 5.
    Expected 1 is nz(true) under that rule, not a value copied from this run.
    """

    libs = {"user/Lib/1": library(_NZ_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [1]


def test_v6_consumer_v5_library_bool_cast_of_na_stays_na() -> None:
    """v5 bool(na) is na, so na(bool(na)) is true.

    Authority: pinelib pine_bool_cast returns na for na when version <= 5,
    and false in v6. Expected 1 is that v5 rule, not a copied runtime value.
    """

    libs = {"user/Lib/1": library(_BOOL_CAST_BODY, version=5)}
    compiled, linked = compile_linked(script("plot(lib.flag())", version=6), libs)
    assert linked.receipt()["sources"]["user/Lib/1"]["pine_version"] == 5
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [1]
