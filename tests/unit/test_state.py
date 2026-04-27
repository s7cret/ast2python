from ast2python.ast.schema import ASTNode
from ast2python.context import TranslationContext
from ast2python.state import state_id_for_call


def test_state_id_stability_and_loc_ordinal():
    ctx = TranslationContext()
    node = ASTNode(
        {
            "kind": "CallExpr",
            "span": {"start_line": 12, "start_col": 6},
            "source": "ta.ema(close, 20)",
        }
    )
    assert state_id_for_call(ctx, node, "ema") == "L12_C6_ema_1"
    assert state_id_for_call(ctx, node, "ema") == "L12_C6_ema_2"


def test_state_id_hash_fallback_is_stable():
    ctx = TranslationContext()
    node = ASTNode({"kind": "CallExpr", "source": "ta.ema(close, 20)"})
    first = state_id_for_call(ctx, node, "ema")
    second = state_id_for_call(TranslationContext(), node, "ema")
    assert first == second
    assert first.startswith("N")
