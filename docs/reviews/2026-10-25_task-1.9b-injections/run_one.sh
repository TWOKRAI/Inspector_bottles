#!/usr/bin/env bash
# Phase 2: run_one.sh <ID|BASE>  -- apply patch (unless BASE), gate-run both files, revert, log.
# Output: raw pytest to scratchpad/runs/<ID>.log ; exit code of the gate on the last line of stdout.
SP="C:/Users/INNOTECH/AppData/Local/Temp/claude/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/c4986ddc-1044-4641-982d-92b139347ba5/scratchpad"
WT=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.claude/worktrees/lso-1.9b-inj
PY=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe
FILES="multiprocess_framework/modules/process_manager_module/process/process_manager_process.py multiprocess_framework/modules/process_manager_module/core/child_process_stop.py multiprocess_framework/modules/process_manager_module/core/process_registry.py multiprocess_prototype/orchestrator.py"
ID="$1"; TAG="${2:-$1}"
mkdir -p "$SP/runs"
export PYTHONUTF8=1
cd "$WT" || exit 1
git diff --quiet -- $FILES || { echo "DIRTY before $ID"; exit 3; }
if [ "$ID" != "BASE" ]; then git apply "$SP/inj/$ID.patch" || { echo "apply failed"; exit 4; }; fi
cd "$WT/multiprocess_framework/modules" || exit 1
PYTHONPATH="$WT" bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" --timed medium inspector-bottles-b4 "$PY" -m pytest process_manager_module/tests/test_lifecycle_fifo_acceptance.py process_manager_module/tests/test_lifecycle_fifo_hazards.py -q --tb=line -p no:cacheprovider -rf > "$SP/runs/$TAG.log" 2>&1
RC=$?
cd "$WT" && git checkout -- $FILES
git diff --stat -- $FILES | tail -1
echo "gate_rc=$RC  log=$SP/runs/$TAG.log"
grep -E "^FAILED|passed|failed|error" "$SP/runs/$TAG.log" | tail -20
