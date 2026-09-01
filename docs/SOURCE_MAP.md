# Source Map v2

`openpine.source_map.v2` contains one entry per IR node:

```text
ir_id
source_node_id
python_line
exact producer span
```

The verifier requires exact fields, unique IR/source identities, unique positive Python
lines, a valid content hash and complete coverage of the LoweringPlan.
