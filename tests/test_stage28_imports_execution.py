"""Stage 2.8 generated-path matrix for locked imports and artifact identity."""

from __future__ import annotations

import pytest
from pine2ast.libraries import LibraryError

from tests.test_locked_library_execution import (
    advance,
    compile_linked,
    library,
    runtime_for,
    script,
)


@pytest.mark.parametrize("version", [5, 6])
def test_stage28_imported_function_udt_enum_and_method_execute(version):
    libs = {
        "user/Lib/1": library(
            "export enum Side\n    buy\n    sell\n"
            "export type Point\n    int n=1\n"
            "export method bump(Point self)=>self.n+1\n"
            "export add(int x)=>x+2",
            version=version,
        )
    }
    compiled, linked = compile_linked(
        script(
            "p=lib.Point.new()\nplot(lib.add(1))\nplot(p.bump())\nplot(lib.Side.buy==lib.Side.buy)",
            version=version,
        ),
        libs,
    )
    runtime, cls = runtime_for(compiled)
    out = advance(runtime, cls, [1])
    assert out[0] == 3
    assert out[1] == 2
    assert out[2] is True
    assert "user/Lib/1" in linked.dependency_hashes


@pytest.mark.parametrize("version", [5, 6])
def test_stage28_transitive_source_change_invalidates_artifact(version):
    base = {"u/Types/1": library("export type Box\n    int n=0\nexport make()=>Box.new()", name="Types", version=version)}
    forwarding = library("import u/Types/1 as types\nexport get()=>types.make()", version=version)
    src = script("p=lib.get()\nplot(p.n)", version=version)
    first, first_link = compile_linked(src, {**base, "user/Lib/1": forwarding})
    changed, changed_link = compile_linked(
        src,
        {**base, "user/Lib/1": forwarding, "u/Types/1": base["u/Types/1"].replace("n=0", "n=7")},
    )
    runtime, cls = runtime_for(first)
    assert advance(runtime, cls, [1]) == [0]
    runtime, cls = runtime_for(changed)
    assert advance(runtime, cls, [1]) == [7]
    assert first.emitted.code_hash != changed.emitted.code_hash
    assert first.artifact.payload["build_determinism_identity"] != changed.artifact.payload["build_determinism_identity"]
    assert first_link.dependency_hashes != changed_link.dependency_hashes


def test_stage28_unresolved_and_private_imports_fail_closed():
    with pytest.raises(LibraryError):
        compile_linked(script("plot(lib.add(1))"), {})
    with pytest.raises(LibraryError):
        compile_linked(
            script("plot(lib.hidden(1))"),
            {"user/Lib/1": library("hidden(int x)=>x\nexport pub(int x)=>x")},
        )
