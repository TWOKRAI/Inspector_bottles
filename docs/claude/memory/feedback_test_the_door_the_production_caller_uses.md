---
name: feedback_test_the_door_the_production_caller_uses
description: "Тест вошёл мимо двери / entry point, которой пользуется боевой вызывающий: зелёный, а фича живьём не работала. Входить через router.receive / настоящий key-event / реальную смерть процесса и утверждать эффект, а не факт отправки"
module: [router_module, process_module]
mechanism: [test-doubles, test-assertions]
metadata:
  type: feedback
---

**Ловушка.** Юнит звал handler напрямую или через фейк, а боевой вызывающий идёт другой дорогой. Тест зелёный, живая система не работает.

**Признак.** «Все тесты зелёные, а на стенде не срабатывает». Три независимых случая:

1. constructor-master Ф3.7: авто-рестарт (монитор -> PM) живьём никогда не работал. `_dispatch_due_restarts` слал `type="system"`; после P4.4.1(B2) `process.command` стала командой CommandManager и до CM не доходила. Юнит Ф3.1 проверял факт отправки IPC, не исполнение. Поймала только fault-injection с реальной смертью процесса (kill -> новый pid).
2. backend-control-mcp P1 (`a6f0221a`): встроенные команды регистрировались после единственного `register_commands_with_router()`, в router их не было, IPC-команды молча дропались. P1-юниты звали handler через фейк.
3. cross-tab G.4.4: два параллельных undo. Глобальный `QShortcut` в MainWindow затенял domain-undo, виден только в живом GUI. Тесты звали handler напрямую.

**Правило.** Входить через дверь боевого вызывающего: `router.receive`, настоящий key-event, реальная смерть процесса. Утверждать эффект (новый pid, дельта state), а не факт отправки. Рядом: брать настоящие orchestrator + store + EventBus вместо `MagicMock(spec=...)`.

**Источник:** сводка аудита 2026-10-04 (`plans/2026-10-04_atlas/research/memory/CONSOLIDATED.md` §1.1, L1) по трём STATE-файлам, ушедшим в `_archive/` (`project_constructor_master_progress`, `project_backend_control_mcp`, `project_cross_tab_phase_g`). Коммиты и фазы из этих файлов не перепроверялись в коде при записи.

Соседи: [[feedback_two_tests_enter_from_both_sides_and_miss_the_connector]], [[feedback_a_stand_with_a_verdict_is_also_a_harness]], [[feedback_qt_mcp_smoke_verification]].
