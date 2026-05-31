# Handoff — Pipeline live-control, Этап 2 (новый чат)

**Дата:** 2026-05-31 · **Ветка:** `feat/pipeline-live-control`

## Этап 1 — ЗАВЕРШЁН (вживую проверено)

Коммиты на ветке:
- `72919883` IPC-мост GUI→ProcessManager (ProcessManagerProxy через RuntimeDeps) + кнопки Pipeline (Перезапустить / Старт-Стоп-Рестарт процесса) + unwrap_recipe фикс редактора
- `434c1249` **fix:** `protected` протащен через схемы (ProcessConfig/ProcessLaunchConfig → top-level proc_dict) → «Перезапустить» НЕ трогает gui (проверено: `protected=['gui']`, окно живо)
- `658be4bb` Recipes: «Загрузить» (=применить) + «Сохранить» (живой граф → рецепт)
- `ac666829`/`76fddf16`/`74ab0449` лог-шум INFO→DEBUG (терминал 62/с → 1/с, всё через LoggerManager)
- `5cfae985` frame-trace snapshot (FrameTraceChannel, overwrite per-frame, env `INSPECTOR_FRAME_TRACE=1`)
- `3defc142` memory

Транспорт: `CommandSender.send_system_command({"cmd": ..., ...})` → `_handle_process_command` → CommandManager. Dict at Boundary.

## Этап 2 — ПЕРЕОСМЫСЛЕН владельцем (НЕ начинать с full-replace)

**Видение владельца (важно, это направление):**
> Нода = плагин, привязан к процессу и воркеру в pipeline.
> 1. **Изменение параметров:** правка внизу графа → сообщение в RouterManager с АДРЕСОМ (процесс → воркер → плагин) + ключ + значение. Знаем куда слать.
> 2. **Добавление ноды:** слать процессу команду «создать воркер» / «добавить плагин в воркер» (в зависимости от последовательности). Процесс ждёт новую итерацию и применяет. Остальные процессы работают как работали — без перезапуска.

**Это правильнее моего предложения** «replace_blueprint целиком» (которое моргает всей цепочкой). Инкрементально, без рестарта соседей, на границе итерации процесса.

**Мой отвергнутый вариант (full-replace-debounced):** надёжно, но перезапускает всю цепочку на каждую правку. Отвергнут в пользу видения владельца.

**Почему НЕ `apply_topology_diff`/`hot_add`:** `build_hot_add_process` (frontend_module/bridge/system_commands.py:64) несёт только ОДИН `plugin_name` — не собирает многоплагинную ноду. Тупик.

## Что УЖЕ ЕСТЬ под видение владельца (переиспользовать, не писать заново)

- **Per-process worker CRUD команды** — `process_module/commands/builtin_commands.py`: `worker.create` / `worker.remove` / `worker.update` / `worker.restart` / `worker.stop` (зарегистрированы, `_cmd_worker_create` и т.д.). Процесс создаёт/убирает воркер без рестарта себя. ⭐ Это основа «добавить ноду = создать воркер в процессе».
- **Изменение параметра вживую** — `SetPluginConfig` → `PluginConfigChanged` → `rm.set_value` → IPC (app.py:476-490). Адресует процесс+поле; нужно дорастить до процесс→воркер→плагин.
- **WorkerManager** — реальные потоки, CRUD воркеров (memory [[project_workers_architecture]]).
- **Иерархическая адресация** — memory [[project_hierarchical_addressing]]: адрес Message иерархический (процесс→воркер→глубже). Целевая транспортная архитектура «Router-хаб + каналы» = `plans/2026-05-31_transport-router-hub/` **P3** (granular live по адресу) — это транспортная сторона того же.
- **ProcessManagerProxy** (Этап 1) — добавить методы адресных команд (worker.create/SetPluginConfig по адресу).

## Открытые вопросы для нового чата

1. **«Добавить плагин в существующий воркер»** — есть `worker.create` (новый воркер), но есть ли «добавить плагин в цепочку существующего воркера»? Проверить commands + PluginOrchestrator. Если нет — это новый тонкий command-handler в процессе.
2. **Маппинг нода↔воркер.** Сейчас нода = плагин внутри process-контейнера (memory [[project_pipeline_node_plugin_containers]], node_id={proc}.{plugin}). Нужна модель «плагин→воркер» в графе (плагин привязан к воркеру).
3. **Применение на границе итерации** — воркеры крутят loop; create/remove воркера применяется на следующем цикле естественно. Подтвердить, что не рвёт полукадры (Этап 3 risk: консистентность, полукадры).
4. **Адресный контракт параметров** — расширить SetPluginConfig-путь до (process, worker, plugin, field, value). Синхронизировать с transport-router-hub P3.

## Указатели на файлы

| Что | Где |
|-----|-----|
| GUI proxy | `multiprocess_prototype/frontend/bridge/process_manager_proxy.py` |
| Worker CRUD команды | `multiprocess_framework/modules/process_module/commands/builtin_commands.py` |
| SetPluginConfig live-путь | `app.py:476-490`, presenter `_on_inspector_field_changed` |
| Backend command-приём | `process_manager_process.py:806 _handle_process_command` |
| Pipeline presenter/tab | `multiprocess_prototype/frontend/widgets/tabs/pipeline/` |
| Связанные планы | `plans/2026-05-31_transport-router-hub/` (P3), `plans/2026-05-31_pipeline-live-control/phase-2.md`, `phase-3.md` |

## Связанные memory

[[project_pipeline_live_control_stage1]], [[project_hierarchical_addressing]], [[project_workers_architecture]], [[project_pipeline_node_plugin_containers]], [[project_transport_router_hub]], [[project_priority_product_over_engine]]
