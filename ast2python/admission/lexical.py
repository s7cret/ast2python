"""Admission of the producer's explicit per-occurrence lexical identity contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ast2python.admission.canonical import canonical_json_bytes
from ast2python.errors import BundleInvariantError

CAPABILITIES = ["implicit_lexical_binder_ids_v1", "lexical_binding_ids_v1"]
SYMBOL_CONTRACT = {
    "identifier_declarations": "exact_declaration_fact_symbol_id",
    "scope": "variables_parameters_tuple_targets_implicit_binders",
    "callable_references": "resolved_call_facts",
    "implicit_binders": {
        "for_in": "user:forinstructure:<name>:<owner_node_id>:role:target",
        "for_range": "user:forrangestructure:<name>:<owner_node_id>:role:iterator",
        "method_receiver": "user:methodreceiver:<name>:<owner_node_id>:role:receiver",
    },
    "version": "1",
}


def admit_lexical_contract(payload: Mapping[str, Any]) -> bool:
    present = {"capabilities", "symbol_id_contract"}.intersection(payload)
    if not present:
        return False  # Explicit legacy artifact admission; not an exact execution fallback.
    if (
        present != {"capabilities", "symbol_id_contract"}
        or canonical_json_bytes(payload["capabilities"]) != canonical_json_bytes(CAPABILITIES)
        or canonical_json_bytes(payload["symbol_id_contract"])
        != canonical_json_bytes(SYMBOL_CONTRACT)
    ):
        raise BundleInvariantError("A2P_LEXICAL_CONTRACT", "unsupported lexical binding contract")
    return True
