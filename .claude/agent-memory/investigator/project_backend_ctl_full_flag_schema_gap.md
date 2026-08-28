---
name: backend-ctl-full-flag-schema-gap
description: full=true escape hatch реально работает только у 3 из 50 MCP-инструментов (system_overview/state_get_subtree/telemetry_history) — у остальных 44 схема отвергает full=true, хотя dispatch.py их всё равно усекает и врёт тем же текстом подсказки. Подтверждено HEAD d37735c6, 2026-08-28
metadata:
  type: project
---

**Факт (ВОСПРОИЗВЕДЕНО, не предположение).** `backend_ctl/dispatch.py::_cap_heavy` (267-293)
байт-капит (`RESPONSE_BYTE_CAP=12000`) ЛЮБОЙ инструмент не из `_UNCAPPED_TOOLS =
{events, events_page, register_snapshot}` (mcp_tools.py:52) и ВСЕГДА пишет подсказку
`"full=true — полный объём"`. Но `input_schema` (`_obj()`, `additionalProperties: False` по
умолчанию) объявляет свойство `full` только у 3 инструментов из 50: `system_overview`
(mcp_tools.py:450), `state_get_subtree` (:732), `telemetry_history` (:1091).

Прогнал офлайн-скрипт (без сети, без бэкенда — чистая `jsonschema.validate` против
`build_registry()[name].input_schema`, тот же путь, что `mcp==1.27.1`
(`mcp/server/lowlevel/server.py::call_tool`, `validate_input=True` по умолчанию) реально гоняет
ДО вызова хендлера): **44 из 50 инструментов дают `jsonschema.ValidationError: Additional
properties are not allowed ('full' was unexpected)`** на `{..., "full": true}` — включая
`capabilities`, `introspect_telemetry`, `session_log`, `send_command`, `state_get`,
`register_restore`, все `record_*`. Скрипт: см. воспроизведение в отчёте ревью
2026-08-28 (scratchpad `ctl/prove_full_schema_block.py`, не сохранён в репо — воспроизвести
заново несложно, 30 строк).

Особенно показателен `session_log` — комментарий САМОГО dispatch.py (309-312) признаёт: «до
~1.6МБ в контекст агента без opt-in full=true», но у `session_log` в схеме нет `full` вовсе
(только `limit`).

**Why:** это тот же баг, что нашёл MCP surface audit 2026-07-23 ([[project_backend_ctl_mcp_surface_audit_2026_07_23]],
тогда «45 из 49»), и это же Н-E / HR-5 из ревью 2026-08-12 (`docs/reviews/2026-08-12_observability-hard-review.md`)
— **план `plans/observability-dx.md` (трек Г) назвал его открытой развилкой владельца
«решить при 6.4» ещё 2026-08-12, и на HEAD 2026-08-28 (16+ дней, 72 коммита в backend_ctl)
решения так и нет.** Три независимых замера за 5 недель фиксируют один и тот же дефект —
не флуктуация, а незакрытый долг.

**How to apply:** при следующей правке `mcp_tools.py`/`dispatch.py` — либо добавить `"full": _FULL`
в схему всех 44 инструментов (механически, но множит поверхность), либо сделать текст подсказки
в `_cap_heavy` условным на `name in _FULL_CAPABLE_TOOLS` (честнее, меньше строк). НЕ доверять
докстрокам README/AGENTS.md «full=true — полный объём» без сверки со схемой конкретного
инструмента — они говорят правду только для 3 из 50.
