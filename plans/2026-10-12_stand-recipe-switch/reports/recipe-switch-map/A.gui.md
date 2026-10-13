# Срез A — GUI-сторона смены рецепта (Explore/haiku, 2026-10-13)

Сырой отчёт агента-разведчика для схемы `docs/maps/recipe-switch.md`. Выводы без запуска помечены.

**0. Имя кнопки.** `multiprocess_prototype/frontend/widgets/tabs/recipes/tab.py:372-378`: «Раньше «Сделать активным»; переименовано» → `QPushButton("Загрузить")` → `_on_activate_clicked`. Старое имя осталось в `tab.py:8`, `view.py:46`, `scripts/run_sim_all.ps1:5,13,121`.

## 1. Шаги (Qt main-thread, кроме пула)
1. Клик: `tab.py:457-461` → `presenter.on_set_active(slug)`.
2. Guards: `presenter.py:332-341` — нет slug → ошибка; `_apply_in_flight` → отказ.
3. RS-4 dirty-диалог: `presenter.py:347-370`, модальный, ДО любых побочных эффектов; «Сохранить» — синхронная запись (`:352-368`).
4. Store: `presenter.py:381-386` `store.set_active(slug)` → `adapters/stores/recipe_store.py:133-142` → `RecipeManager.set_active` (запись на диск не проверена).
5. Домен: `presenter.py:388-403` `dispatch(ActivateRecipe(slug), undoable=False)` синхронно; исключение → `store.set_active(prev)`. Домен: `domain/entities/project.py:388-389`, `_apply_activate_recipe` :918.
6. Upsert устройств ДО apply: `presenter.py:410-425` → `tab.py:419-426` `send_action_command("devices","device_sync_set",…)` — fire-and-forget через PM-relay.
7. Чтение raw, выбор источника топологии: `presenter.py:430-445` (v3 → весь raw dict, иначе blueprint).
8. Busy + async apply: `presenter.py:447-453` (`_apply_in_flight=True`, кнопка «Применяется…» `tab.py:316-330`); исключение → откат `:455-459`.
9. Прокси: `tab.py:124-126` → `process_manager_proxy.py:73-98` → `_dispatch_async("topology.apply", {"topology_dict": source})` (`:94,97,154-158`).
10. Пул: `process_manager_proxy.py:158` `runner.submit(...)` → `request_runner.py:87-100` `QThreadPool.globalInstance()` → `command_sender.py:253-282` `router.request(msg, timeout=30.0)`; ожидание `router_manager.py:1084-1101` `pending.event.wait`.
11. Доставка: `request_runner.py:49-50,102-106` → main-thread → `presenter._on_apply_result` (`presenter.py:470-513`).
12. Успех: `presenter.py:485-500` → `_finalize_activation` (`:515-529`): запись манифеста, `load()`.
13. Провал: `presenter.py:502-513` → `_rollback_activation` (`:531-555`).
Попутно: `app.py:702-706` (`RecipeActivated` → `topology_session.mark_activated`), `app.py:1003-1007` (`_rebuild_displays`).

## 2. Payload'ы
- Конверт `message_module/builders/command_envelopes.py:57-90`: `command:"process.command"`, `targets:["ProcessManager"]`, `data:{cmd,…}`; `router_manager.py:1065-1071` добавляет `request_id`, `correlation_id`.
- `data = {"cmd":"topology.apply","topology_dict":…,"correlation_id":…}` — **`recipe_path` НЕ отправляется**; `process_manager_process.py:780` `args.get("recipe_path") or ""` → ретаргет в `""` (`:795` откат при неуспехе) — R-11.
- До apply: `command_sender.py:97-110` → `process.relay` → `devices` / `device_sync_set`.
- PM: `process_manager_process.py:3248-3328` → `_cmd_topology_apply` (:751-796) → `apply_topology` (:3842); ответ `reply_to_request` (:3322-3326).

## 3. Модальные окна
RS-4 (`tab.py:293-306`, `unsaved_changes.py:27+`) — до backend-вызова. Во время ожидания backend модальных окон нет. Ошибки — `QMessageBox.warning` (`tab.py:308-314`).

## 4. Ошибка, таймаут, поздний ответ
- Таймаут: `router_manager.py:1101` → `{"success":False,"error":"timeout"}` → `_rollback_activation`.
- Откат (`presenter.py:540-555`): `store.set_active(prev)`/`deactivate()`, компенсирующий `dispatch(ActivateRecipe(prev))`, `show_error`, `load()`.
- НЕ откатывается: upsert `devices` (уже отправлен). Манифест не пишется (только при успехе, `:521-523`).
- **Поздний ответ** (вывод из кода): `router_manager.py:1111-1113` удаляет pending; `_resolve_pending` (`:1234-1236`) → False → `frontend/process.py:100, 212-240` `_on_command_response` только логирует. GUI откатился, а PM мог применить топологию — сверки нет; отмены на PM нет.
- Отказ PM: `debounced` (`process_manager_process.py:807-814`) или `error`+`rolled_back` (`:3905-3928`, `:4020-4032`).
- Риск вечного «Применяется…» (вывод из кода): `_apply_in_flight` сбрасывается только в `_on_apply_result` и в `except` отправки; доставка `request_runner.py:49-64` «не безотказна».

## 5. Параллельные команды в PM во время смены
- `process.relay` → `devices` (`device_sync_set`), live field-write `register_update` (`app.py:757-762`, через relay).
- `TelemetryPoller` (`app.py:384-400`) — `introspect.telemetry` прямо процессам, timeout 3 с, пул из 2 потоков.
- Вкладка процессов (`processes/presenter.py:140,166,189`) — только по действию пользователя.
- Блокировки других кнопок GUI на время apply нет; PM отвечает `debounced` на параллельный `topology.apply`.

## 6. Маркеры
`presenter.py:613` `TODO: Task 7a` (не на пути). `command_sender.py:31` `DEFAULT_REQUEST_TIMEOUT = 30.0` = `frontend_module/DECISIONS.md:101`.

## Что осталось открытым
`RecipeManager.set_active` (пишет ли диск), `project.py:918-959` целиком, верхняя граница `apply_topology` в PM (`_wait_started_ready` :4162, окно `start_ready_timeout_s`, дефолт 0.5 с по докстрингу), адресация позднего ответа — не проверены; тесты не запускались.
