---
name: project_runtime_knob_expires_in_300s
description: Рантайм-правка телеметрии живёт 300 с и умирает молча — посылка «гейт закрыт» имеет срок годности
metadata:
  node_type: memory
  type: project
  originSessionId: 2b72a30f-3ef0-4501-b07f-415e482f0987
  modified: 2026-08-17T07:41:24.449Z
---

`telemetry_set` (и вообще `telemetry.reconfigure`) кладёт правку не в гейт, а в **сессионный слой
L3 со сроком 300 с по умолчанию**. Подметальщик на такте heartbeat снимает истёкший ключ и
пересобирает гейт из слоёв; так как в `multiprocess_prototype/backend/config/system.yaml:176-182`
секция `telemetry:` закомментирована, boot-слоя под правкой нет — и пересборка отдаёт `None`, то
есть **снимает гейт целиком** (`gate_active: true → false`, `publish: null`, без рестарта).

Цепочка: `process_heartbeat.py:183` (`_sweep_observability_session`) → `managers/observability_ttl.py:91`
→ `managers/observability_reload.py:1115-1118` (липкий `telemetry_owned` + `boot_sub is None`) →
`managers/telemetry_reload.py:117` → `process_heartbeat.py:537-539`.

**ПОПРАВКА 2026-08-18 (замер стенда `logs_live/stage6_stand_20260818`): срок ТЕПЕРЬ
объявляется, и это главное изменение к записи ниже.** В момент истечения процесс пишет
WARNING в свой `system.log`, называя откатившиеся ключи поимённо и подсказывая, чем продлить:

```
[WARNING] [gui] observability: [observability] TTL истёк — рантайм-правки возвращены к
нижнему слою: telemetry.publish.default_enabled, telemetry.publish.default_interval_sec,
telemetry.publish.metrics; действующий log_level=INFO; ещё держится сессией: —.
Чтобы правка жила дольше — ttl=<сек> при смене или observability.persist в рецепт
```

Отсюда две правки к рецептам ниже: **искать надо `"TTL истёк"` в `<процесс>/system.log`**,
а не `expire origin=ttl-sweeper` в `messages.log` (этой строки нет — grep по ней даёт ноль
на всех восьми процессах и читается как «не истекало», хотя истекло на семи). И срабатывает
подметальщик **у каждого процесса своим тактом**: 18:16:00.103 (`devices`) … 18:16:01.976
(`camera_0`) — разброс 1.9 с, то есть гейт снимается не мгновенно и не одновременно.

**Чем это кусает измерение.** На том же подъёме TTL снял гейт за 0.5–2.4 с ДО того, как
пришла моя команда снятия, — и «обратный контроль» оказался сделан подметальщиком, а не
командой. Наблюдение «гейт открыт → трафик вернулся» устояло, атрибуция «его вернула моя
команда» — нет. Планируя пару ON/OFF, ставь окно заведомо короче 300 с ЛИБО передавай явный
`ttl`, иначе вторая половина пары окажется чужой работой.

Ниже — исходная запись 2026-08-17, верная во всём, кроме абзаца про молчание:

Оператору про срок **не говорили** (на 2026-08-17): ребёнок его считает и отдаёт (`ttl_sec`,
`builtin_commands.py:2334-2340`), но адресный путь идёт транзитом через PM fire-and-forget и
проекция PM (`process_manager_process.py:3081-3096`) поле не несёт; `introspect.telemetry` блока
сроков не имеет, хотя `ttl_report` уже подмешан в соседний `introspect.observability`. Заведено
T-1…T-4 в `plans/QUEUE.md`.

**Why:** шесть подряд `telemetry_set(..., verify=true)` вернули `verified_effect: true`, и ни один
не сказал «умрёт через 300 с». Гейт снялся через 5 минут, и это выглядело спонтанной поломкой
publisher-гейта — то есть подрывало все живые доказательства, опирающиеся на «гейт закрыт».

**How to apply:** окно измерения короче 300 с — считать как есть. Длиннее — передавать явный `ttl`
через `send_command telemetry.reconfigure` (у `telemetry_set` ручки `ttl` в MCP-схеме нет) либо
перед вердиктом сверять `introspect.observability → session_ttl` и `grep "TTL истёк" в <процесс>/system.log (рецепт исправлен 2026-08-18, см. поправку выше; строки expire origin=ttl-sweeper НЕТ)`
в `messages.log` адресата. **`session_log` тут не доказательство:** он видит мутации только своей
сессии, а подметальщик — не команда, а хозяйственное дело такта, и в нём не появляется никогда.
Истечение умеет только СНЯТЬ гейт (метрика пойдёт каждый тик), поэтому наблюдение «в дереве
заморожено» им не объясняется — а вот «неожиданно поехало» объясняется. См.
[[feedback_a_knob_can_be_applied_and_unverifiable]], [[project_backend_ctl_signal_integrity]],
[[feedback_diagnose_live_system_with_backend_ctl]].
