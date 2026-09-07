"""Declaration evidence comes from checked source, before any values are created."""

import ast
import hashlib
import json
from dataclasses import replace
from importlib.resources import files

import pytest
from pinelib.reference.registry import NominalTypeRegistry

from ast2python import BundleInvariantError
from ast2python.admission.canonical import canonical_json_bytes
from ast2python.artifacts import verify_generated_artifact_v3
from ast2python.artifacts.nominal_registry import admitted_nominal_registry
from ast2python.lowering import load_pinelib_target_manifest
from tests.test_locked_library_execution import compile_linked, library, script
from tests.test_rc6_input_metadata import compile_source

CAPABILITY = "compiler.nominal_registry.v1"


def source(body, version=6):
    declaration = "indicator" if version >= 5 else "study"
    return f'//@version={version}\n{declaration}("registry")\n{body}\n'


def admit(result):
    envelope = result.artifact.payload
    verify_generated_artifact_v3(envelope, plan=result.plan, emitted=result.emitted)
    assert (
        "sha256:" + hashlib.sha256(result.emitted.code.encode("utf-8")).hexdigest()
        == envelope["emitted_module_hash"]
    )
    namespace = {}
    exec(compile(result.emitted.code, "registry.py", "exec"), namespace)
    return namespace, admitted_nominal_registry(namespace, envelope)


def declared_id(result, name, kind):
    nodes = [
        node
        for node in result.plan.nodes.values()
        if node.attributes.get("ast_kind") == kind and node.attributes["fields"]["name"] == name
    ]
    assert len(nodes) == 1
    prefix = "enum" if kind == "EnumDeclaration" else "udt"
    return f"{prefix}:{result.plan.source_hash}:{name}:{nodes[0].source.node_id}"


@pytest.mark.parametrize("version", [5, 6])
def test_unused_declarations_full_member_order_titles_and_field_schema_are_literal(version):
    result = compile_source(
        source(
            'enum Side\n    z = "Long"\n    a = ""\n    middle\n'
            "type Box\n    Side side\n    varip int ticks=0\n    array<float> samples\n"
            "type Unused\n    Box nested\n"
            "Side typed_na=na\nempty=array.new<Box>()\nplot(na(typed_na))",
            version,
        )
    )
    # Read a literal, not a callback or GeneratedScript constructor side effect.
    assignments = [
        node
        for node in ast.parse(result.emitted.code).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "NOMINAL_TYPE_REGISTRY"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    literal = ast.literal_eval(assignments[0].value)
    enum = declared_id(result, "Side", "EnumDeclaration")
    box = declared_id(result, "Box", "TypeDeclaration")
    unused = declared_id(result, "Unused", "TypeDeclaration")
    assert literal == {
        "schema_id": "pinelib.nominal_registry.v1",
        "pine_version": version,
        "source_hash": result.plan.source_hash,
        "types": sorted(
            [
                {
                    "id": enum,
                    "kind": "enum",
                    "members": [
                        {"name": "z", "title": "Long"},
                        {"name": "a", "title": ""},
                        {"name": "middle", "title": "middle"},
                    ],
                },
                {
                    "id": box,
                    "kind": "udt",
                    "fields": [
                        {"name": "side", "type": enum, "varip": False},
                        {"name": "ticks", "type": "int", "varip": True},
                        {"name": "samples", "type": "array<float>", "varip": False},
                    ],
                },
                {
                    "id": unused,
                    "kind": "udt",
                    "fields": [{"name": "nested", "type": box, "varip": False}],
                },
            ],
            key=lambda row: row["id"],
        ),
    }
    namespace, registry = admit(result)
    assert type(registry) is NominalTypeRegistry
    assert registry.to_json() == literal
    assert CAPABILITY in result.plan.required_capabilities
    assert CAPABILITY in result.artifact.payload["required_capabilities"]
    assert registry.enum_member(enum, "a", 1).title == ""
    assert namespace["GeneratedScript"](None).runtime is None


@pytest.mark.parametrize("version", [5, 6])
def test_forward_and_cyclic_type_fields_use_the_complete_declaration_identity_set(version):
    result = compile_source(
        source(
            "type First\n    Second next\n"
            "type Second\n    First previous\n"
            "First absent=na\nplot(na(absent))",
            version,
        )
    )
    _, registry = admit(result)
    first = declared_id(result, "First", "TypeDeclaration")
    second = declared_id(result, "Second", "TypeDeclaration")
    assert registry.udt_schema(first).fields[0].type.text == second
    assert registry.udt_schema(second).fields[0].type.text == first


@pytest.mark.parametrize("version", [5, 6])
def test_linked_private_helper_declaration_closure_and_unused_members_survive(version):
    lib = library(
        'enum Internal\n    first = "Private"\n    unused = "Still declared"\n'
        "type Local\n    Internal side=Internal.first\n    int n=7\n"
        "export value()=>\n    p=Local.new()\n    p.n",
        version=version,
    )
    result, linked = compile_linked(
        script("plot(lib.value())", version=version), {"user/Lib/1": lib}
    )
    _, registry = admit(result)
    rows = registry.to_json()["types"]
    assert len(rows) == 2
    enum, udt = rows
    assert enum["kind"] == "enum" and udt["kind"] == "udt"
    assert enum["members"] == [
        {"name": "first", "title": "Private"},
        {"name": "unused", "title": "Still declared"},
    ]
    assert udt["fields"] == [
        {"name": "side", "type": enum["id"], "varip": False},
        {"name": "n", "type": "int", "varip": False},
    ]
    assert registry.source_hash == linked.receipt()["linked_source_hash"]
    assert all(row["id"].startswith(row["kind"] + ":" + registry.source_hash + ":") for row in rows)


@pytest.mark.parametrize("version", range(1, 7))
def test_nonnominal_generated_module_retains_explicit_legacy_compatibility(version):
    result = compile_source(source("plot(close)", version))
    namespace, registry = admit(result)
    assert "NOMINAL_TYPE_REGISTRY" not in namespace
    assert CAPABILITY not in result.artifact.payload["required_capabilities"]
    assert registry is None


@pytest.mark.parametrize("version", [5, 6])
def test_nominal_operation_requires_registry_capability_in_addition_to_old_contract(version):
    from pine2ast.hardening.consumer_bundle import build_consumer_bundle

    from ast2python import compile_consumer_bundle

    target = load_pinelib_target_manifest()
    assert "compiler.nominal_types.v1" in target.capabilities
    with pytest.raises(BundleInvariantError, match="A2P_PLAN_CAPABILITY"):
        compile_consumer_bundle(
            build_consumer_bundle(source("enum Side\n    buy\ne=Side.buy", version)),
            target=replace(target, capabilities=target.capabilities - {CAPABILITY}),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        (None, None),
        ("revision", True),
        ("revision", 2),
        ("min_pine_version", 5.0),
        ("identity", "learned-from-callbacks"),
        ("admission", "after-restore"),
        ("unknown", True),
    ],
)
def test_additive_registry_manifest_contract_is_exact_and_fail_closed(tmp_path, field, value):
    manifest = json.loads(
        files("pinelib.abi").joinpath("target_manifest.json").read_text(encoding="utf-8")
    )
    assert CAPABILITY in load_pinelib_target_manifest().capabilities
    if field is None:
        manifest.pop("compiled_nominal_registry")
    else:
        manifest["compiled_nominal_registry"][field] = value
    body = {key: value for key, value in manifest.items() if key != "content_hash"}
    manifest["content_hash"] = "sha256:" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    path = tmp_path / "target.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert CAPABILITY not in load_pinelib_target_manifest(path).capabilities
