# Phase 2 — Config-driven discovery + PluginManager

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/discovery-config-paths`
> **Дней**: 2-3
> **Зависимости**: Phase 0
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-2-discovery-config-paths.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

Убрать хардкод `PLUGINS_DIR = PROJECT_ROOT / "Plugins"` из `main.py`. Пути живут в `backend/config/system.yaml` (правильный путь!) и редактируются из GUI через перенесённый из backup `PluginManager`.

## Реюз готового

- `PluginRegistry.discover(*dirs)` — уже принимает varargs.
- `PluginManager` (Phase 0, из backup) — auto-discovery + hot-reload.
- `ConfigManager` + `config.subscribe()` для реактивности.

## Файлы

- `multiprocess_prototype/backend/config/system.yaml` — добавить:
  ```yaml
  discovery:
    plugin_paths: ["Plugins"]
    service_paths: ["Services"]
  ```
- `multiprocess_prototype/backend/config/user_overrides.yaml` (опц., gitignored) — для GUI-правок путей.
- `multiprocess_prototype/main.py` и `frontend/app.py` — заменить хардкод на `config.discovery.plugin_paths`.
- Подвкладка «Пути» в `frontend/widgets/tabs/plugins/`:
  - Список путей + кнопки «Добавить папку», «Удалить», «Рескан».
  - На «Рескан» → `PluginManager.rescan()` → событие `state.plugins.catalog_updated`.
- Каталог в PluginManagerTab подписан на это событие.

## Acceptance

- Добавление пути через GUI → плагины из новой папки видны в каталоге без рестарта.
- Настройки персистятся.
- 5-7 unit-тестов на PluginManager + integration на подвкладку.
