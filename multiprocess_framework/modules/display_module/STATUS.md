# display_module — Статус компонентов

**Статус:** ACTIVE (Phase 4 — DisplayRegistry + DisplaysTab)
**Фаза:** Phase 4 — DisplayRegistry + DisplaysTab
**Дата создания:** 2026-05-25

Модуль декларативного реестра именованных SHM-каналов для отображения кадров. `DisplayRegistry` — thread-safe singleton с YAML-персистентностью. Generic-контракт: без vision-семантики (`element_shape`, `dtype`). Фактическое создание SHM-сегмента — ответственность `SharedResourcesManager` при старте `ProcessManagerProcess` (ADR-025).

---

## Таблица компонентов

| Компонент | Файл | Статус | Описание |
|-----------|------|--------|----------|
| DisplayEntry | interfaces.py | Готов | dataclass конфига дисплея: id, name, width, height, format, fps_limit, ring_buffer_blocks |
| IDisplayRegistry | interfaces.py | Готов | Protocol (runtime_checkable): register, unregister, get, list, persist |
| IDisplayChannel | interfaces.py | Готов | Protocol (runtime_checkable): channel_key, subscribe, unsubscribe, is_active |
| DisplayRegistry | registry.py | Готов | Singleton-реестр с double-checked locking + YAML persist/load |

**Тестов:** 12 (Task 4.8, `tests/test_registry.py` — готово, коммит `8c41ea1b`)

---

## Статус интеграции

| Компонент | Интеграция | Статус |
|-----------|------------|--------|
| **interfaces.py** | DisplayEntry dataclass | Готов |
| | IDisplayRegistry Protocol | Готов |
| | IDisplayChannel Protocol | Готов |
| **registry.py** | DisplayRegistry singleton + persist/load YAML | Готов |
| **DisplaysTab** | `multiprocess_prototype/frontend/widgets/tabs/displays/` | Готов (Task 4.2) |
| **blueprint_binding.py** | `multiprocess_prototype/backend/displays/blueprint_binding.py` | Готов (Task 4.3) |
| **PreviewWindow** | `multiprocess_prototype/frontend/widgets/displays/preview_window.py` | Готов (Task 4.7) |

---

## TODO (отложено в Phase 7+)

- **Конкретная реализация `IDisplayChannel`** — Protocol объявлен, конкретная реализация (в `RouterManager` или prototype-обёртке) запланирована в Phase 7 (PipelineTab + Display-узлы).
- **IPC-синхронизация дисплеев** — `DisplayStateAdapter` синхронизирует `DisplayRegistry ↔ state.displays.*`; в GUI-процессе `StateProxy` работает в no-op режиме аналогично Phase 3 (ServiceStateAdapter), полноценная IPC-синхронизация в Phase 7+.

---

## Известные ограничения

- `_cleanup_shm_channel` при `unregister` — **только лог-предупреждение**. Фактическое освобождение SHM происходит при следующем рестарте `ProcessManagerProcess` (ADR-DM-003). До рестарта возможна короткая зомби-память.
- `IDisplayChannel` Protocol объявлен, но конкретной реализации в framework нет — реализация в `RouterManager` или prototype-обёртке (Phase 7).
- `clear()` предназначен только для изоляции тестов; в production вызывать не следует.
- Vision-поля (`element_shape`, `dtype`) в `DisplayEntry` **отсутствуют** намеренно (ADR-DM-001) — они вычисляются prototype-слоем при создании SHM-сегмента.

---

## История выпусков

| Дата | Событие | Статус |
|------|---------|--------|
| 2026-05-25 | Task 4.1: interfaces.py — DisplayEntry, IDisplayRegistry, IDisplayChannel | Готово |
| 2026-05-25 | Task 4.2: registry.py — DisplayRegistry singleton + persist/load YAML | Готово |
| 2026-05-25 | Task 4.3: blueprint_binding.py — bind_displays_to_blueprint в prototype | Готово |
| 2026-05-25 | Task 4.9: README.md + STATUS.md + DECISIONS.md (ADR-DM-001/002/003) + глобальный ADR-130 | Готово |
