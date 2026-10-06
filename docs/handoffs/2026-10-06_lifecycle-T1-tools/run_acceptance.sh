#!/usr/bin/env bash
# Приёмка T1 числами (шаги 1–3 хендоффа 2026-10-06_lifecycle-T1-lead.md) одной командой, без агентов.
# Запуск (Git Bash, из любого места):  bash docs/handoffs/2026-10-06_lifecycle-T1-tools/run_acceptance.sh
# Длительность ~3–3.5 ч. Нужно: машина не засыпает; в окна стенда (последний ~час) не кликать; без чужих тяжёлых прогонов.
# Итог — в C:/tmpa4/acceptance.log; полный вывод гейтов — C:/tmpa4/gate-*; логи стенда — C:/tmpstand/S*.
set -u
MAIN=D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles
TREE=$MAIN/.claude/worktrees/lifecycle
PY=$MAIN/.venv/Scripts/python.exe
TOOLS=C:/tmpa4/tools
LOG=C:/tmpa4/acceptance.log
export PYTHONUTF8=1

mkdir -p "$TOOLS" C:/tmpa4
for f in stand_t1.py stand_entry.py; do cp "$TREE/docs/handoffs/2026-10-06_lifecycle-T1-tools/$f.txt" "$TOOLS/$f"; done
cd "$TREE" || exit 1
A=scripts/gc_policy_acceptance.py
S=$TOOLS/stand_t1.py

{
  echo "START $(date '+%F %T') HEAD $(git rev-parse --short HEAD)"
  if netstat -ano | grep -qE ":876[5-9] .*LISTEN"; then echo "ПОРТ 8765–8769 ЗАНЯТ — чужой стенд? Остановка."; exit 1; fi

  echo "=== 1. гейт native x3";    $PY $A gate -n 3 --timeout 2400 --save-dir C:/tmpa4/gate-native
  echo "=== 2. гейт offscreen x2"; $PY $A gate -n 2 --offscreen --timeout 2400 --save-dir C:/tmpa4/gate-off

  echo "=== 3. контроль D3: база C:/lcb против HEAD, вперемешку, offscreen"
  for set in process router state; do for i in 1 2 3; do
    echo "$set #$i BASE: $($PY $A $set -n 1 --offscreen --timeout 1800 --root C:/lcb | grep SUMMARY)"
    echo "$set #$i HEAD: $($PY $A $set -n 1 --offscreen --timeout 1800 | grep SUMMARY)"
  done; done

  echo "=== 4. стенд D2: 2 прогона x 3 режима, автологин"
  cp "$MAIN/multiprocess_prototype/dev_settings.py" multiprocess_prototype/dev_settings.py
  for i in 1 2; do
    $PY "$S" S$i-freeze0 600 INSPECTOR_AUTH_DEV_AUTO_LOGIN=1 INSPECTOR_GC_OBSERVE=1 FW_GC_FREEZE=0 2>&1
    $PY "$S" S$i-freeze1 600 INSPECTOR_AUTH_DEV_AUTO_LOGIN=1 INSPECTOR_GC_OBSERVE=1 FW_GC_FREEZE=1 2>&1
    $PY "$S" S$i-nopolicy 600 INSPECTOR_AUTH_DEV_AUTO_LOGIN=1 INSPECTOR_GUI_GC_POLICY=0 2>&1
  done
  rm -f multiprocess_prototype/dev_settings.py
  git status --short | grep -v agent-memory
  echo "DONE $(date '+%F %T')"
} 2>&1 | tee "$LOG"
