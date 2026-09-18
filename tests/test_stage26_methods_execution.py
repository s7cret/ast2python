"""Stage 2.6 generated-path matrix for method resolution, defaults and state."""

from __future__ import annotations

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pine2ast.libraries import LibraryError

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)
from tests.test_nominal_language_execution import source, trace
from tests.test_rc6_input_metadata import compile_source


@pytest.mark.parametrize("version", [5, 6])
def test_stage26_receiver_defaults_named_args_and_returns(version):
    body = (
        "type A\n    int n=1\ntype B\n    int n=10\n"
        "method score(A self, int step=2)=>self.n+step\n"
        "method score(B self, int step=3)=>self.n*step\n"
        "plot(A.new().score())\nplot(B.new().score(step=4))"
    )
    assert trace(body, version) == [3, 40] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_stage26_written_method_callsites_keep_independent_state(version):
    body = (
        "type P\n    int n=0\n"
        "method count(P self, int step=1)=>\n    var int seen=0\n    seen+=step\n    seen\n"
        "p=P.new()\nplot(p.count())\nplot(p.count(2))"
    )
    # Two written callsites: +1 and +2 per bar.
    assert trace(body, version) == [1, 2, 2, 4, 3, 6]


@pytest.mark.parametrize("version", [5, 6])
def test_stage26_loop_reuses_one_callsite_state(version):
    body = (
        "type P\n    int n=0\n"
        "method count(P self)=>\n    var int seen=0\n    seen+=1\n    seen\n"
        "p=P.new()\nn=0\nfor i=1 to 3\n    n:=p.count()\nplot(n)"
    )
    assert trace(body, version) == [3, 6, 9]


@pytest.mark.parametrize("version", [5, 6])
def test_stage26_collection_method_does_not_use_udt_namesake(version):
    body = (
        "type Bag\n    int n=7\n"
        "method measure(Bag self)=>self.n\n"
        "method measure(array<int> self)=>array.size(self)+100\n"
        "plot(Bag.new().measure())\nplot(array.new<int>(2).measure())"
    )
    assert trace(body, version) == [7, 102] * 3


@pytest.mark.parametrize("version", [5, 6])
def test_stage26_exported_library_methods_do_not_mix_receivers(version):
    libs = {
        "ownerA/Lib/1": library(
            "export type Point\n    int n=1\nexport method score(Point self)=>self.n",
            name="Lib",
            version=version,
        ),
        "ownerB/Lib/1": library(
            "export type Point\n    int n=10\nexport method score(Point self)=>self.n*3",
            name="Lib",
            version=version,
        ),
    }
    imports = "import ownerA/Lib/1 as a\nimport ownerB/Lib/1 as b"
    compiled, _ = compile_linked(
        script("plot(a.Point.new().score())\nplot(b.Point.new().score())", imports, version),
        libs,
    )
    runtime, cls = runtime_for(compiled)
    assert advance(runtime, cls, [1]) == [1, 30]
    with pytest.raises((ConsumerBundleError, LibraryError)):
        compile_linked(script("plot(b.score(a.Point.new()))", imports, version), libs)


@pytest.mark.parametrize(
    "body",
    [
        "f(int x)=>x\nplot(1.f())",
        "method choose(int self, int n)=>n\nmethod choose(int self, int other)=>other\nplot(1.choose(2))",
        'method read(array<int> self)=>array.get(self,0)\nplot(array.new<string>(1,"x").read())',
        "method score(A self)=>1\nplot(score())",
    ],
)
def test_stage26_illegal_resolution_rejected_before_execution(body):
    with pytest.raises(ConsumerBundleError):
        compile_source(source(body))
