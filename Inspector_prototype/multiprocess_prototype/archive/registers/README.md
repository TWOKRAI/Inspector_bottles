# Регистры прототипа Inspector

Доменные схемы регистров живут в **`schemas/`** (по фичам) и наследуют `SchemaBase` из `data_schema_module`. Это код приложения, не фреймворка. Подписи экранов без `register_update` — рядом с виджетом во `frontend/widgets/<feature>/`.

## Схемы

| Пакет | Регистры | Процесс |
|-------|----------|---------|
| `schemas/processing_tab/` | ProcessorRegisters, RendererRegisters | processor, renderer |
| `schemas/camera_tab/` | CameraRegisters | camera |

## Файлы

- Фабрика: `factory.py` → `RegistersManager` + `connection_map`. Полная картина связки схем, UI и YAML-рецептов при старте GUI: [../docs/SCHEMA_REGISTERS_UI_INIT.md](../docs/SCHEMA_REGISTERS_UI_INIT.md).
- Маршрутизация GUI-команд: `command_routing.py` → `resolve_command_targets(command_id)` из `RegisterDispatchMeta` схем + `EXPLICIT_COMMAND_TARGETS` (например `system.shutdown` → ProcessManager). Каталог payload: `gui_command_catalog.py` (`GUI_COMMAND_CATALOG`); отправка — `frontend/commands/gui_command_handler.py` и `backend/gui_process_mixin.py`.
- Чеклист нового поля: `CHECKLIST.md`
- Boot-значения для процессов (синхронно с регистрами):
  - `schemas/processing_tab/boot.py` — processor_process_boot_values, renderer_process_boot_values
  - `schemas/camera_tab/boot.py` — camera_process_boot_values

См. **ADR-050** в `multiprocess_framework/DECISIONS.md`.

---

## История рефакторинга (сводка)

**Изменяемые параметры в схемах:** CameraRegisters (`schemas/camera_tab/`), расширенные RendererRegisters (draw_bboxes, save_frames); конфиги процессов берут boot из `*_process_boot_values()`, а не дублируют поля. Settings tab привязан к processor/renderer.

**GUI-команды и backends (2026-03):** единый `resolve_command_targets` в `command_routing.py`, каталог `GUI_COMMAND_CATALOG`, `GuiProcessMixin._send_command` использует тот же resolver. Бэкенды захвата: `backend/modules/camera/backends.py`. В `registers/__init__.py` — ленивые импорты `create_registers` / схем для лёгких unit-тестов routing/catalog.

**Рекомендации по развитию**

- Камера: команды (start/stop, enum_devices) и `register_update` для camera_type/fps/resolution — гибрид осознанный; при необходимости проверить `receive_message(timeout=0)` в capture_worker на блокировки.
- Новые поля: схема → boot → `register_sync` → UI; см. `CHECKLIST.md`.
- При расширении RendererRegisters (например output_dir) — та же цепочка.

Оценка паттерна регистров (историческая, 1–10): единый источник истины и boot ~9, тестируемость ~8, обратная совместимость (callbacks, сохранение camera_type через `persistence`) ~7; **среднее ~8.4**.
