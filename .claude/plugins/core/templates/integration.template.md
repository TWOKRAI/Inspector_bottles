# Integration Report — {{TASK_ID}} ({{DATE}})

## Summary

VERDICT: PASS | BLOCK
Reason: (if BLOCK — one line)

## Machine-readable gate data

> integrator fills this block; integration_gate.py reads ONLY this JSON, not the
> prose sections below. Keep every key present and the JSON syntactically valid.

```json
{
  "cycles_new": [],
  "coverage_before": 0.0,
  "coverage_after": 0.0,
  "coverage_delta": 0.0,
  "godnode_growth_pct": 0,
  "mcp_available": true
}
```

When `mcp_available` is `false`, record `"cycles_new": []`,
`"coverage_delta": 0.0`, `"godnode_growth_pct": 0` — the gate then sees an
advisory PASS with no false enforcement.

## Dependency cycles

- New cycles introduced: none | list
- Baseline cycles: N, After: M

## God-node analysis

- Flagged modules (>20% growth in fan-in): none | list with before/after metrics

## Coverage delta

- Before: X% | After: Y% | Delta: Z%
- Threshold: max -5% allowed

## Dead/dup/CRAP signals

- Dead code added: none | list
- CRAP score regressions: none | list

## MCP tools used

- sentrux:dsm — available | unavailable (fallback: Grep)
- codegraph_explore — available | unavailable (fallback: Read)

## Raw evidence

(relevant excerpts from sentrux/codegraph output)
