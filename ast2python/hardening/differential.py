from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from ast2python.admission.ast_view import StrictASTNode
from ast2python.admission.facts import SemanticFactView
from ast2python.lowering.recipes import select_recipe


@dataclass(frozen=True, slots=True)
class DifferentialCase:
    case_id: str
    left_version: int
    right_version: int
    feature: str
    left_opcode: str
    right_opcode: str
    expected_relation: str
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "left_version": self.left_version,
            "right_version": self.right_version,
            "feature": self.feature,
            "left_opcode": self.left_opcode,
            "right_opcode": self.right_opcode,
            "expected_relation": self.expected_relation,
            "passed": self.passed,
        }


def _fact(kind: str) -> SemanticFactView:
    return SemanticFactView(
        node_id="n",
        node_kind=kind,
        classification="EXPRESSION",
        resolved_type=None,
        scope_id="scope:global",
        symbol_id=None,
        overload_id=None,
        call_form=None,
        receiver_type=None,
        coercions=(),
        semantic_rule_ids=(),
        stateful_call=False,
        raw=MappingProxyType({}),
    )


def _node(kind: str, **fields: Any) -> StrictASTNode:
    return StrictASTNode(
        node_id="n",
        kind=kind,
        span=MappingProxyType(
            {
                "start_offset": 0,
                "end_offset": 1,
                "start_line": 1,
                "start_col": 1,
                "end_line": 1,
                "end_col": 2,
            }
        ),
        fields=MappingProxyType(fields),
        child_node_ids=(),
    )


def _opcode(version: int, feature: str) -> str:
    if feature in {"and", "or", "div"}:
        op = "/" if feature == "div" else feature
        node = _node("BinaryExpr", op=op)
    elif feature == "conditional":
        node = _node("ConditionalExpr")
    elif feature == "for_range":
        node = _node("ForRangeStructure")
    else:
        raise AssertionError(feature)
    return select_recipe(version=version, node=node, fact=_fact(node.kind), call=None).opcode


def run_version_differential() -> tuple[DifferentialCase, ...]:
    cases: list[DifferentialCase] = []
    for left, right in ((1, 2), (2, 3), (3, 4), (4, 5), (5, 6)):
        for feature in ("and", "or", "div", "conditional", "for_range"):
            left_op = _opcode(left, feature)
            right_op = _opcode(right, feature)
            should_differ = (feature == "conditional" and left <= 3 < right) or (
                feature in {"and", "or", "div", "for_range"} and left <= 5 < right
            )
            relation = "DIFFERENT" if should_differ else "SAME"
            passed = (left_op != right_op) if should_differ else (left_op == right_op)
            cases.append(
                DifferentialCase(
                    case_id=f"v{left}-v{right}-{feature}",
                    left_version=left,
                    right_version=right,
                    feature=feature,
                    left_opcode=left_op,
                    right_opcode=right_op,
                    expected_relation=relation,
                    passed=passed,
                )
            )
    return tuple(cases)
