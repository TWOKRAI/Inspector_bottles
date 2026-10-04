---
name: feedback-backend-ctl-for-agents
description: "Тестировать/отлаживать бэкенд агентам через backend_ctl (имитация фронтенд-сообщений), НЕ через запуск GUI и НЕ через qt-mcp; также: Живую систему диагностировать штатным backend_ctl, а не самописными psutil-скриптами — инструмент для этого и сделан"
merged_from: [feedback_diagnose_live_system_with_backend_ctl]
metadata:
  node_type: memory
  type: feedback
  originSessionId: 05a29a24-fbc4-4241-8e6f-a55d2a6b5db0
---

Директива владельца (2026-07-06): backend_ctl существует ИМЕННО для того, чтобы агенты
тестировали бэкенд, имитируя сообщения фронтенда, — без запуска самого фронтенда и без qt-mcp.

**Why:** driver шлёт те же router-сообщения, что GUI через CommandSender («GUI по сокету») —
это быстрее, стабильнее и не требует Qt-окружения; qt-mcp — только для проверки самого GUI.

**How to apply:** для любой проверки бэкенда (команды, state, introspect, логи) — BackendDriver
(`backend_ctl/AGENTS.md` — рецепт) или BackendHarness-фикстура (Ф1.3+); qt-mcp звать только
когда проверяется виджет/layout. После Ф1.7 — MCP-инструменты backend_ctl напрямую.
См. [[project-constructor-master-progress]].

## Слито из feedback_diagnose_live_system_with_backend_ctl (_archive/feedback_diagnose_live_system_with_backend_ctl.md)

Владелец, увидев мою попытку снять состояние зависшего процесса самописным psutil-скриптом:
«я думал для этого и был backend_ctl чтобы выявлять проблемы». Правка принята и оказалась
короче: `system_overview` + `supervision_status` + `get_status` за три вызова показали то,
на что скрипт не отвечал вовсе — что процесс `gui` при боевом запуске **жив и отвечает**,
а значит дефект не в GUI, а в моём пути подъёма.

**Why:** самописный зонд отвечает на вопрос, который я уже сформулировал, и потому
подтверждает мою же гипотезу. Штатный инструмент отвечает на вопросы, которые я не задал:
`anomalies`, `late_replies`, `backend_warming`, список немых ручек поимённо. Плюс он —
единственная дорога внутрь через RouterManager, то есть меряет систему так, как её видят
её собственные потребители.

**How to apply:** для живой системы порядок такой — `capabilities` (контактная книжка),
`system_overview` (вердикты, не археология), затем адресные `introspect_*` по подозреваемому
и **по соседям** (молчание одного адреса и молчание стенда — разные факты). Самописный
скрипт оправдан только там, куда backend_ctl не дотягивается по построению, и это надо
уметь назвать вслух. Бэкенд для этого поднимается с `BACKEND_CTL=1`.

Родня: [[project_backend_ctl_framework_module]], [[project_backend_ctl_signal_integrity]],
[[feedback_single_marker_verdict_lies]], [[project_gui_stand_production_entry_only]].
