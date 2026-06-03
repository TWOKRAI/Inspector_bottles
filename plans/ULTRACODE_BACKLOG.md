# Ultracode backlog — список задач под мульти-агентный залп

> **Что это.** Накопитель задач, которые имеет смысл закрывать **ultracode-workflow** (параллельный fan-out + worktree-изоляция + adversarial-ревью), а не по одной в max-режиме.
> **Правило отбора.** Сюда — только *независимые, специфицированные* задачи (много мелочи, которую можно распараллелить). Глубокие root-cause-баги (один последовательный «инструментируй→запусти→читай»-цикл) ultracode НЕ ускоряет — они помечены ⚠️ и по-хорошему решаются отдельно.
> **Когда запускать.** Я подам сигнал, когда наберётся критическая масса **fan-out-friendly** задач (ориентир: ≥4-5 независимых пунктов). Команда залпа — `ultracode` в запросе.

**Источник:** `plans/comm-system-target-architecture.md` (P0), HANDOFF `plans/2026-06-03_telemetry-backend-control-HANDOFF.md`.
**Ветка:** `feat/comm-system-target-architecture`.

---

## ✅ Fan-out-friendly (целевые для ultracode)

| # | Задача | Файлы / scope | Источник |
|---|--------|---------------|----------|
| ~~1~~ | ~~**M5 целиком** — мёртвый wire `router_manager`/`enable_router_routing`/`messages_routed`~~ ✅ **СДЕЛАНО 2026-06-03 (max)** — оказалось не fan-out-задачей: 4 файла + interfaces docstring, единый последовательный проход; см. «Лог решений» | logger_manager + error_manager + logger_adapter + process_managers | HANDOFF §UNCOMMITTED |
| 2 | **§11 quick-wins** — пачка независимых мелочей | п.2/3/4/11/13/14/16-19 | plans/comm-system §11 |
| 3 | **Потеря сообщений** — `_route_to_worker` (критичный) | п.20-22 | plans/comm-system §11 |
| 4 | **RolesPanel / get_field** | п.5/6 | plans/comm-system §11 |

---

## ⚠️ Deep root-cause (решены в max-режиме — подтверждают тезис «ultracode не для этого»)

| # | Задача | Статус | Итог |
|---|--------|--------|------|
| T1 | **Телеметрия `state.*` timeout** — `state.subscribe`/`state.get` к ProcessManager → timeout, introspect отвечает. | ✅ **РЕШЕНО 2026-06-03 (max)** | Серверный root-cause: конфликт RAW↔wrapped регистрации в `message_dispatcher` (RAW не зовёт `reply_to_request`, побеждает по «первая регистрация»). Фикс `auto_register_ipc=False`. Verified probe'ом: state.* отвечают, ProcessMonitor публикует. Подробно — `plans/comm-system-target-architecture.md` (P0, 2026-06-03) + memory `project_telemetry_subscription_bug`. **Подтверждает тезис:** глубокий single-path баг решается одним последовательным циклом, не fan-out'ом. |

---

## Заметки по диагностике T1 (чтобы не терять контекст)

Прочитано на момент фиксации (для будущего исполнителя):
- `_extract_data` (state_store_manager.py:123) корректно достаёт `msg["data"]` если dict, иначе сам msg → **гипотеза (a) о несовпадении сигнатуры выглядит маловероятной** (data-поле обрабатывается).
- `_make_command_handler._handler` (process_lifecycle.py:144): `result = cm.handle_command(msg)` → `router.reply_to_request(msg, result)` только если у входящего билета есть correlation-id. **Проверить: state.subscribe от probe несёт ли correlation-id?** Если нет — reply молча не отправляется (fire-and-forget), отсюда timeout у драйвера.
- `telemetry_probe` шлёт через `drv.send_command(... timeout=6.0)` — request/reply ожидает reply по request_id.
- → **Сильная рабочая гипотеза:** `introspect.*` идут как `drv.request` (несут correlation-id → reply уходит), а `drv.send_command` для state.* НЕ проставляет correlation-id → `reply_to_request` делает no-op → timeout. Различие не в RAW-vs-wrapped, а в **наличии correlation-id у исходящего билета** (совпадает с симптомом из HANDOFF: «различие специфично, но не RAW-vs-wrapped»). Проверять с этого.

---

## Лог решений

- **2026-06-03** — список заведён. Владелец: копить hard-баги и независимую мелочь, запуск ultracode — когда я подам сигнал. Телеметрия (T1) отложена в backlog вопреки моей рекомендации добить сразу.
- **2026-06-03** — **M5 закрыт в max-режиме** (ultracode не запускался). Удалён мёртвый router-wire из пути логирования: `enable_router_routing`/`router_manager`-параметры, `observable_config["router_routing"]`, атрибут `_router_manager`, стат `messages_routed`, метод `LoggerAdapter.set_router_routing`, проброс в `ErrorManager`, `enable_router_routing=True` в `process_managers`. Тесты 286 зелёные (logger+error+process), ruff clean. **Вывод:** задача была *не* fan-out-friendly (один связный wire через 4 файла + наследование Error←Logger) — правильно сделана одним проходом, а не залпом.
