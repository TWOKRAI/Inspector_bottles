---
description: Run the Debugger agent (Sonnet) — diagnose failing tests, regressions, puzzling errors
---

Run the **debugger** agent (Sonnet) to diagnose the problem.

Input: $ARGUMENTS — description of the bug, a reproduction command, or a path to the failing test.

## Algorithm

1. **Check the arguments**
   If $ARGUMENTS is empty:
   > Specify the problem: `/dev:debug <description>` or `/dev:debug pytest <path>::<test>`
   > For example: `/dev:debug pytest tests/test_router.py::test_channel_dispatch`

2. **Gather context**
   - Recent commits: `git log -5 --oneline`
   - Recent changes: `git diff HEAD~1` (if a regression)
   - If there's a failing test: `pytest <path> -v -x --tb=short` (short traceback)

3. **Call the debugger**
   ```
   Agent(subagent_type: "debugger", prompt: "<description + gathered context>", run_in_background: false)
   ```
   Synchronous call — the diagnosis is needed to decide the next step in the same turn.

4. **Handle the result**
   - If **FIXED** → the debugger fixed and committed everything itself
   - If **ROOT CAUSE FOUND** (without a fix) → hand the diagnosis to the right agent:
     - Junior/Middle level → `developer` (Sonnet)
     - Senior+ level → `teamlead` (Opus)
   - If it **didn't reproduce** → tell the user an exact scenario is needed

## Typical calls

```
/dev:debug pytest tests/unit/test_models.py::test_spec_from_dict
/dev:debug test_workspace_flow fails after merging main
/dev:debug AttributeError in gui/toolbar_router.py while loading a project
```

## When NOT to call

- An obvious typo → just fix it yourself
- The task isn't implemented yet → that's not debug, that's implement
- A full refactor is needed → that's teamlead, not debugger

## Automatic activation

`/dev:pipeline` automatically calls the debugger on a FAIL from the tester (iterations 1 and 2). A manual `/dev:debug` is needed when the `/dev:pipeline` cycle isn't running, or the Director wants a diagnosis outside the pipeline.
