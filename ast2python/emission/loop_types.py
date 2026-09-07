"""Typed missing loop/block values, preserving tuple arity without evaluation."""

from ast2python.errors import BundleInvariantError


def missing_value_expression(dtype: str, version: int) -> str:
    if not dtype.startswith("tuple<"):
        return "False" if dtype == "bool" and version >= 6 else "_PineLibNA"
    if not dtype.endswith(">"):
        raise BundleInvariantError("A2P_LOOP_RETURN_TYPE", "malformed tuple result")
    inner = dtype[6:-1]
    depth, begin, values = 0, 0, []
    for i, char in enumerate(inner):
        depth += (char == "<") - (char == ">")
        if depth < 0:
            raise BundleInvariantError("A2P_LOOP_RETURN_TYPE", "malformed tuple result")
        if char == "," and depth == 0:
            values.append(inner[begin:i].strip())
            begin = i + 1
    values.append(inner[begin:].strip())
    if depth or not all(values):
        raise BundleInvariantError("A2P_LOOP_RETURN_TYPE", "empty tuple result type")
    return "(" + ", ".join(missing_value_expression(t, version) for t in values) + ",)"
