---
name: project_state_topology_gate
description: Гейт FW_STATE_TOPOLOGY_GATE отбрасывает записи в processes.<name>.* для процессов вне текущей топологии — закрыл воскрешение призраков после switch
metadata:
  type: project
---

После switch в дереве оставались процессы старого рецепта — **каждый прогон разные**, без `pid`/`config`, из одних обрывков телеметрии. Не «cleanup не отработал» (тогда остались бы все), а гонка: `_delete_process_state` сносит поддерево, а `state.set` от умирающего инстанса доезжает следом и создаёт узел заново.

Закрыто `TopologyGateMiddleware` (ADR-SS-019, `state_store_module/middleware/topology_gate.py`) + флаг `FW_STATE_TOPOLOGY_GATE` (дефолт ON) + перестановка в `_topology_cleanup`: конфиг снимается ПЕРЕД cleanup, иначе остаётся окно, где процесс ещё «известен» гейту.

**Why:** fencing эту дыру не закрывает по устройству — он про ЗАМЕНУ инстанса (incarnation растёт), а снятый switch'ем процесс удалён, его incarnation никто не бампит.

**How to apply:** приёмка гонок — только парой ON/OFF, не одиночным зелёным (флаг=1 → 4/4 зелёных, флаг=0 → призраки 2/2). Одиночный зелёный прогон на гонке ничего не доказывает. См. [[project_fencing_test_race]].
