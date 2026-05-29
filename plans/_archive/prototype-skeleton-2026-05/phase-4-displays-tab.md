# Phase 4 — DisplayRegistry + DisplaysTab переписать

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/displays-tab`
> **Дней**: 5-7
> **Зависимости**: Phase 0
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

Отдельная вкладка для CRUD дисплеев. Дисплей = именованный SHM-канал (через перенесённую из backup инфраструктуру `shm/registry.py` + `frame_router_setup.py`). GUI-окно подписано на канал через subscribe-паттерн.

## Реальная фундация

- `RingBuffer` — уже в `shared_resources_module/buffers/ring_buffer.py` (готов, не трогаем).
- `RouterManager.register_broadcast_route(channel, subscribers)` — уже умеет fan-out broadcast (готов). FrameRouter из Phase 0 — это лишь helper-обёртка.
- `shared_resources_module` + ADR-025 — config-driven memory.
- Текущий `tabs/displays/presenter.py` — слотовые пресеты (1x1/2x2) **БЕЗ persistence**. Полностью переписать.

## Новое (framework)

- `multiprocess_framework/modules/display_module/interfaces.py` — `IDisplayRegistry`, `IDisplayChannel` Protocol. Контракт намеренно generic: `slot_size_bytes`, `element_shape`, `dtype` (vision-specific image semantics — на уровне prototype-обёртки, не в framework-контракте). ADR-решение по семантике в `display_module/DECISIONS.md`.
- `multiprocess_framework/modules/display_module/registry.py` — `DisplayRegistry` (конкретная реализация):
  - `DisplayEntry(id, name, width, height, format, fps_limit, ring_buffer_blocks)`.
  - `register/unregister/list/get` + persist в `multiprocess_prototype/backend/config/displays.yaml`.
  - При регистрации дисплея — запись в blueprint memory: `ui_process.memory["display_<id>"] = {blocks, frame_shape: (h, w, c)}` (config-driven path ADR-025).
- `multiprocess_prototype/frontend/widgets/tabs/displays/`:
  - `tab.py` (переписать) — `DisplaysTab(BaseListNavTab)` + `DisplaysPresenter`.
  - Левый список дисплеев, правая панель — форма (имя, размер, формат, fps_limit, ring_buffer_blocks).
  - Кнопки: «Создать», «Удалить», «Дублировать», **«Открыть превью»** (создаёт `PreviewWindow` подписанное на канал — для проверки без полного pipeline).
  - Опционально (после MVP): layout-композитор — несколько дисплеев в одно окно через пресеты 1x1/2x2 (наследуем из текущего slot-механизма как ОТДЕЛЬНУЮ фичу).
- `multiprocess_prototype/frontend/widgets/displays/preview_window.py` — окно с QLabel, подписанное на SHM-канал через `frame_router.subscribe()`.
- `multiprocess_prototype/backend/state/adapters/display_state_adapter.py` — sync DisplayRegistry ↔ `state.displays.*`.
- ADR в `multiprocess_framework/DECISIONS.md`: «DisplayRegistry: декларативный реестр SHM-каналов через RouterManager + frame_router_setup, не плагин».

## Расширение StateStore bootstrap

- `multiprocess_prototype/backend/state/bootstrap.py` — добавить ветки `state.displays.*` при инициализации.

## Acceptance

- Создать 2 дисплея (main 1280x720, debug 640x480) → они появились в `displays.yaml` и в state-дереве; SHM-каналы создались при следующем старте процессов.
- Открыть превью-окно дисплея → пока на него никто не пишет, окно пустое; после запуска демо (Phase 7) — кадры идут.
- 20-25 unit-тестов на DisplayRegistry, frame_router subscribe, preview_window.
