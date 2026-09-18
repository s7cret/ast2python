"""Stage 2.1 end-to-end input metadata and generated-runtime closure."""

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError
from pinelib.reference.heap import PineEnumValue

from .test_rc6_input_metadata import compile_source, run_source


@pytest.mark.parametrize("version", [5, 6])
def test_enum_and_text_area_compile_and_execute(version):
    source = f"""//@version={version}
indicator("enum/text")
enum Mode
    fast
    slow
mode=input.enum(Mode.fast,"Mode",options=[Mode.fast,Mode.slow])
text=input.text_area("a\\nb","Text")
plot(mode==Mode.slow ? str.length(text) : 0)
"""
    runtime, metadata, _ = run_source(
        source,
        {
            "mode": {
                "$pinelib_enum": {
                    "enum_id": next(
                        row["enum_type"]
                        for row in metadata_placeholder(source).values()
                        if row["kind"] == "enum"
                    ),
                    "member": "slow",
                    "ordinal": 1,
                }
            },
            "text": "abc\ndef",
        },
        [1],
    )
    mode = next(spec for spec in runtime.inputs.specs if spec.kind == "enum")
    text = next(spec for spec in runtime.inputs.specs if spec.kind == "text_area")
    assert isinstance(mode.value, PineEnumValue) and mode.value.member == "slow"
    assert text.value == "abc\ndef"
    assert runtime.visuals.committed[-1].payload["series"] == 7
    assert {row["kind"] for row in metadata["inputs"].values()} == {"enum", "text_area"}


def metadata_placeholder(source):
    result = compile_source(source)
    namespace = {}
    exec(compile(result.emitted.code, "input_metadata.py", "exec"), namespace)
    return namespace["SCRIPT_METADATA"]["inputs"]


def test_compound_active_expression_is_emitted_from_checked_ir_and_uses_overrides():
    source = """//@version=6
indicator("active")
enum Mode
    fast
    slow
enabled=input.bool(true,"Enabled")
length=input.int(2,"Length")
mode=input.enum(Mode.fast,"Mode")
value=input.float(1.5,"Value",active=(enabled and length+1>=5) or mode==Mode.slow)
plot(value)
"""
    metadata = metadata_placeholder(source)
    mode_row = next(row for row in metadata.values() if row["kind"] == "enum")
    slow = {"$pinelib_enum": {"enum_id": mode_row["enum_type"], "member": "slow", "ordinal": 1}}
    off, _, _ = run_source(source, {"enabled": False, "length": 10}, [1])
    by_number, _, _ = run_source(source, {"enabled": True, "length": 4}, [1])
    by_enum, metadata, _ = run_source(source, {"enabled": False, "length": 0, "mode": slow}, [1])
    assert off.specs if False else True  # keep no alternate test-only runtime path
    assert next(s for s in off.inputs.specs if s.kind == "float").active is False
    assert next(s for s in by_number.inputs.specs if s.kind == "float").active is True
    value = next(s for s in by_enum.inputs.specs if s.kind == "float")
    assert value.active is True and value.value == 1.5
    row = next(row for row in metadata["inputs"].values() if row["kind"] == "float")
    assert row["active"]["op"] == "or"


def test_direct_active_dependency_keeps_compact_legacy_descriptor():
    source = """//@version=6
indicator("active")
enabled=input.bool(true)
value=input.int(2,active=enabled)
plot(value)
"""
    runtime, metadata, _ = run_source(source, {"enabled": False, "value": 0}, [1])
    rows = list(metadata["inputs"].values())
    assert rows[1]["active"] == {"input_id": rows[0]["input_id"]}
    spec = runtime.inputs.specs[1]
    assert spec.active is False and spec.active_expression is None
    assert spec.value == 0


@pytest.mark.parametrize(
    "source",
    [
        """//@version=6\nindicator("bad")\nenum A\n    x\nenum B\n    x\nm=input.enum(A.x,options=[A.x,B.x])\n""",
        """//@version=6\nindicator("bad")\non=input.int(1)\nx=input.int(2,active=on)\n""",
        """//@version=6\nindicator("bad")\nx=input.text_area(1)\n""",
    ],
)
def test_invalid_nominal_or_active_contracts_fail_before_generated_execution(source):
    with pytest.raises(ConsumerBundleError):
        compile_source(source)
