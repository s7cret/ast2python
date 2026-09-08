"""Read exact producer-owned canonical variadic metadata for group admission."""

from collections.abc import Mapping
from typing import Any, NoReturn

from pine2ast.catalog import CatalogRepository

from ast2python.admission.ast_view import StrictASTView
from ast2python.errors import BundleInvariantError


def admitted_variadic_parameters(
    call: Mapping[str, Any], version_context: Mapping[str, Any], ast_view: StrictASTView
) -> frozenset[tuple[int, str]]:
    arguments = call.get("arguments", [])
    if not any(row.get("binding") == "vararg" for row in arguments):
        return frozenset()

    def fail(message: str) -> NoReturn:
        raise BundleInvariantError("A2P_CALL_VARIADIC_CONTRACT", message)

    version = version_context.get("pine_version")
    if type(version) is not int or version not in range(1, 7):
        fail("variadic call requires an exact Pine version")
    catalog = CatalogRepository.default().readonly_view(version)
    if catalog["catalog_hash"] != version_context.get("catalog_hash"):
        fail("variadic metadata requires the exact installed producer catalog")
    candidates = [
        row
        for row in catalog["functions"].values()
        if row.get("symbol_id") == call.get("symbol_id")
        and call.get("overload_id") == str(row.get("symbol_id")) + "#canonical"
        and call.get("call_form")
        == ("NAMESPACE_FUNCTION" if "." in row.get("name", "") else "FUNCTION")
    ]
    if len(candidates) != 1:
        fail("variadic call requires one exact canonical producer signature")
    parameters = candidates[0].get("parameters", [])
    groups = {
        (index, row.get("name")): row
        for index, row in enumerate(parameters)
        if row.get("variadic") is True
    }
    if len(groups) != 1 or next(iter(groups))[0] != len(parameters) - 1:
        fail("variadic signature requires one final declared group")
    source_order = tuple(
        child
        for child in ast_view.node(call["node_id"]).child_node_ids
        if ast_view.node(child).kind == "Argument"
    )
    if tuple(row.get("argument_node_id") for row in arguments) != source_order:
        fail("variadic arguments must retain exact source order")
    for row in arguments:
        if type(row.get("parameter_index")) is not int or not isinstance(
            row.get("parameter_name"), str
        ):
            fail("variadic parameter identity must be typed")
        key = (row.get("parameter_index"), row.get("parameter_name"))
        if row.get("binding") == "vararg":
            parameter = groups.get(key)
            if parameter is None or (
                row.get("expected_type") != parameter.get("type")
                or row.get("max_qualifier") != parameter.get("qualifier_max")
            ):
                fail("variadic argument differs from the declared parameter contract")
        elif key in groups:
            fail("variadic group requires positional vararg bindings")
    return frozenset(groups)
