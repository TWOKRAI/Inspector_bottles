# Phase 6 — Sandbox-тест плагина в PluginManagerTab

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/plugin-sandbox`
> **Дней**: 2-3
> **Зависимости**: Phase 3 (для webcam snapshot)
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-6-plugin-sandbox.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

На карточке плагина — кнопка «Тест», открывает мини-панель: вход (файл-изображение или snapshot активного webcam-сервиса) → параметры → «Применить» → preview результата.

## Реюз готового

- `PluginConfigPanel` — редактирование конфига плагина.
- `SubPluginContext` из process_module — изолированный контекст (но с ограничениями — см. ниже).
- `RegistersManager` для валидации параметров.

## Новое

- `multiprocess_prototype/frontend/widgets/tabs/plugins/sandbox.py` — `PluginSandboxWidget`:
  - QFileDialog для изображения **или** snapshot текущего webcam-кадра (через `ServiceRegistry.get("webcam_camera").get_current_frame()`, если сервис RUNNING).
  - Создаёт `SubPluginContext` с mock-`RegistersManager` (для плагинов, которые читают регистры).
  - Вызывает `plugin.process(frame, metadata)` в QThread.
  - Показывает before/after side-by-side через QLabel или существующий `ImagePanelWidget`.
- На карточке плагина кнопка «Тест» открывает sandbox в правой панели.

## Ограничения (явно зафиксировать)

- Sandbox только для **stateless single-frame** плагинов категории `processing` / `render` (gray, color_mask, negative, flip, resize, blur).
- Для `sources` (camera, capture) — кнопка disabled с тултипом «используйте превью сервиса в ServicesTab».
- Для `runtime` (chain_executor, worker_pool) — disabled.
- Для multi-input плагинов (stitcher — собирает несколько регионов) — disabled с пометкой «требует pipeline-контекст».

## Acceptance

- Выбрали `color_mask`, загрузили jpg, покрутили H/S/V → preview обновился.
- Выбрали `stitcher` — кнопка disabled с понятной причиной.
- 10-15 unit-тестов.
