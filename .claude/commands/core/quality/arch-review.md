---
description: Comprehensive architecture review — sentrux health, DSM, test gaps, optional diagrams
---

Comprehensive architecture review of the project.

## What to do

Assemble a single report from three sources:

### 1. Sentrux Health
Run `mcp__sentrux__scan` + `mcp__sentrux__health` — get the metrics:
- modularity, acyclicity, depth, equality
- overall score and grade (A–F)
- bottleneck modules

### 2. Sentrux DSM
Run `mcp__sentrux__dsm` — show:
- cyclic dependencies (if any)
- the most connected modules (fan-in/fan-out)

### 3. Test Gaps
Run `mcp__sentrux__test_gaps` — show:
- modules without tests
- modules with low coverage

### 4. Diagrams (optional)
If `docs/diagrams/classes/` contains .puml files — mention the date of the last generation.
If empty — suggest `make diagrams` or `/core:infra:diagrams`.

## Response format

A structured report (reply language follows the `language` key in settings.json):
- **Health:** score/grade + key metrics
- **Connectivity:** cycles, hot spots
- **Coverage:** gaps
- **Recommendations:** 3-5 concrete actions
