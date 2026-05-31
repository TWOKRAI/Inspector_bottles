---
name: project-pipeline-live-control-stage1
description: Этап 1 pipeline-live-control DONE — IPC-мост GUI→PM + два открытых framework-блокера
metadata:
  type: project
---

Этап 1 плана `plans/2026-05-31_pipeline-live-control/` ЗАВЕРШЁН (commit 72919883, ветка feat/pipeline-live-control).

**Сделано:** `ProcessManagerProxy` (frontend/bridge/process_manager_proxy.py) — тонкий фасад над `CommandSender.send_system_command` (`{"cmd": "blueprint.replace"|"process.start|stop|restart", ...}` → backend `_handle_process_command` → готовые методы PM). Прокинут через `RuntimeDeps.process_manager_proxy` (НЕ через config — `Config.__init__` делает deepcopy, ломает живой CommandSender). Кнопки Pipeline (Перезапустить/Старт/Стоп/Рестарт процесса) + Recipes «Сделать активным» (replace_blueprint_fn). IPC fire-and-forget → proxy возвращает optimistic-ack, UI говорит «команда отправлена».

**Бонус-фикс (app.py блок 3a):** GUI грузил `manifest.pipeline` (= рецепт `recipes/region_pipeline.yaml` с вложенным `blueprint:`) БЕЗ `unwrap_recipe` → редактор видел только `gui` из base.yaml, процессы рецепта терялись. Добавлен `unwrap_recipe` (зеркалит backend launch.py). Теперь редактор = полный граф (8 процессов).

**Два открытых framework-блокера (НЕ pipeline-сторона, follow-up):**
1. **recipe-launch теряет `protected: true`** — base.yaml помечает `gui` protected, но running ProcessManager показывает `protected=[]`. Поэтому «Перезапустить» весь граф рестартит И сам GUI-процесс. Полный smoke «delete→restart→дисплей меняется» этим блокируется. Нужен фикс распространения protected-флага в recipe-driven launch (SystemBuilder/build_configs).
2. Из-за #1 кнопка «Перезапустить» (весь граф live) сейчас деструктивна. Per-process «Стоп/Старт» безопасны (адресуют один процесс).

IPC-мост доказан end-to-end (лог: `command gui -> ['ProcessManager'] cmd=process.command` → `replace_blueprint: начало замены`). Связано: [[project_pipeline_editor_runtime_decoupled]], [[project_pipeline_recipe_driven_launch]].
