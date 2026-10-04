---
name: project-pipeline-live-control-stage1
description: Этап 1 pipeline-live-control DONE — IPC-мост GUI→PM + два открытых framework-блокера
metadata:
  type: project
---

Этап 1 плана `plans/2026-05-31_pipeline-live-control/` ЗАВЕРШЁН (commit 72919883, ветка feat/pipeline-live-control).

**Сделано:** `ProcessManagerProxy` (frontend/bridge/process_manager_proxy.py) — тонкий фасад над `CommandSender.send_system_command` (`{"cmd": "blueprint.replace"|"process.start|stop|restart", ...}` → backend `_handle_process_command` → готовые методы PM). Прокинут через `RuntimeDeps.process_manager_proxy` (НЕ через config — `Config.__init__` делает deepcopy, ломает живой CommandSender). Кнопки Pipeline (Перезапустить/Старт/Стоп/Рестарт процесса) + Recipes «Сделать активным» (replace_blueprint_fn). IPC fire-and-forget → proxy возвращает optimistic-ack, UI говорит «команда отправлена».

**Бонус-фикс (app.py блок 3a):** GUI грузил `manifest.pipeline` (= рецепт `recipes/region_pipeline.yaml` с вложенным `blueprint:`) БЕЗ `unwrap_recipe` → редактор видел только `gui` из base.yaml, процессы рецепта терялись. Добавлен `unwrap_recipe` (зеркалит backend launch.py). Теперь редактор = полный граф (8 процессов).

**Два framework-блокера — ЗАКРЫТЫ (434c1249):**
1. **recipe-launch терял `protected: true`** — корень: `ProcessConfig`/`ProcessLaunchConfig` не имели поля `protected` → SchemaBase отбрасывал его при model_validate. Фикс: добавлено поле `protected` в обе схемы + `build()` кладёт на top-level `proc_dict` + `as_generic_config` пробрасывает. Проверено: running PM теперь `protected=['gui']`, «Перезапустить» НЕ трогает gui (GUI жив). test_protected_propagation (4 кейса).
2. Следствие #1 закрыто: «Перезапустить» весь граф теперь безопасен (gui skip, 7 обрабатывающих заменяются).

**Recipes-кнопки (658be4bb):** «Сделать активным»→«Загрузить» (активирует+применяет к backend, enabled при выборе), новая «Сохранить» (services.topology → выбранный рецепт, on_save).

**Логи через LoggerManager (ac666829/76fddf16/74ab0449):** per-frame флуд (router_messages, InspectorManager timeout flush, [TRACE] DataReceiver/SourceProducer/PipelineExecutor) переведён INFO→DEBUG. Терминал: ~62 строки/с → ~1 строка/с. Всё остаётся в LoggerManager (правило проекта), просто на корректном уровне. Overwrite-snapshot «1 кадр в файл» НЕ сделан — требует LoggerManager-канал (append-only logging не делает overwrite); предложен опцией.

IPC-мост доказан end-to-end (лог: `command gui -> ['ProcessManager'] cmd=process.command` → `replace_blueprint: начало замены`). Связано: [[project_pipeline_editor_runtime_decoupled]], [[project_pipeline_recipe_driven_launch]].
