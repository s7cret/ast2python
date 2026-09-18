"""Re-created 2.1 regression subset; executes generated Pine through real PineLib."""

import pytest
from pine2ast.hardening.consumer_bundle import ConsumerBundleError

from .test_rc6_input_metadata import compile_source, run_source


@pytest.mark.parametrize("version", range(1, 7))
@pytest.mark.parametrize("value,expected", [("2", 2), ("2.5", 2.5), ("false", False)])
def test_named_default_follows_binding_not_title(version, value, expected):
    decl = "indicator" if version >= 5 else "study"
    runtime, metadata, _ = run_source(
        f'//@version={version}\n{decl}("test")\nx=input(title="Title",defval={value})\nplot(x)\n',
        closes=[10],
    )
    spec = runtime.inputs.specs[0]
    assert spec.default == expected and type(spec.default) is type(expected)
    assert spec.kind == {int: "int", float: "float", bool: "bool"}[type(expected)]
    assert list(metadata["inputs"].values())[0]["default"] == expected


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize(
    "kind,default,options,override",
    [("int", "2", "[1,2,3]", 3), ("float", "1.5", "[0.5,1.5,2.5]", 2.5)],
)
@pytest.mark.parametrize("named", [False, True])
def test_numeric_options_have_their_own_signature(version, kind, default, options, override, named):
    tail = (
        f'defval={default},title="Choice",options={options}'
        if named
        else f'{default},"Choice",{options}'
    )
    runtime, metadata, _ = run_source(
        f'//@version={version}\nindicator("test")\nx=input.{kind}({tail})\nplot(x)\n',
        {"x": override},
        [10],
    )
    spec = runtime.inputs.specs[0]
    assert spec.value == override and spec.minimum is None and spec.maximum is None
    assert spec.options == tuple(
        float(x) if kind == "float" else int(x) for x in options[1:-1].split(",")
    )
    assert runtime.visuals.committed[-1].payload["series"] == override


@pytest.mark.parametrize("version", [5, 6])
@pytest.mark.parametrize("arguments", ["close", 'title="S",defval=close'])
def test_generic_source_stays_series_and_obeys_override(version, arguments):
    runtime, _, _ = run_source(
        f'//@version={version}\nindicator("source")\nx=input({arguments})\nplot(x)\n',
        {"x": "high"},
        [10, 20],
    )
    assert runtime.inputs.specs[0].kind == "source"
    assert [e.payload["series"] for e in runtime.visuals.committed] == [11, 21]


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("value", [0, 7])
def test_active_is_bound_to_actual_bool_input_without_disabling_value(enabled, value):
    runtime, metadata, _ = run_source(
        '//@version=6\nindicator("active")\non=input.bool(true)\n'
        'x=input.int(2,active=on,tooltip="Подсказка",display=display.none)\nplot(x)\n',
        {"on": enabled, "x": value},
        [10],
    )
    switch, spec = runtime.inputs.specs
    assert spec.active is enabled and spec.active_input_id == switch.input_id
    assert spec.tooltip == "Подсказка" and spec.display == "display.none"
    assert spec.value == value and runtime.visuals.committed[-1].payload["series"] == value
    assert list(metadata["inputs"].values())[1]["active"] == {"input_id": switch.input_id}


@pytest.mark.parametrize("args", ["defval=close", "2,options=[1,2],minval=1", 'title="Only"'])
def test_invalid_numeric_forms_remain_rejected(args):
    with pytest.raises(ConsumerBundleError):
        compile_source(f'//@version=6\nindicator("negative")\nx=input.int({args})\nplot(x)\n')
