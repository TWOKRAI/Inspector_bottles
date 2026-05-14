# Diagrams — Визуализация архитектуры

Diagrams-as-code: все схемы хранятся как текст, версионируются (ручные) или регенерируются (авто).

## Содержание

### Ручные (в git)

| Файл | Что | Чем открывать |
|------|-----|---------------|
| [`architecture.mmd`](architecture.mmd) | C4 Container-level — общая архитектура проекта | Mermaid Preview (VS Code) |
| [`modules-overview.mmd`](modules-overview.mmd) | **Связи между модулями фреймворка** (6 слоёв) | Mermaid Preview (VS Code) |

### Авто-генерируемые (не в git)

| Каталог | Что | Команда регенерации |
|---------|-----|---------------------|
| `classes/per-module/` | UML классов каждого модуля (22 шт.) | `make diagrams-per-module` |
| `deps/framework-overview.svg` | Полный граф зависимостей фреймворка | `make diagrams-deps` |
| `deps/framework-modules.svg` | Упрощённый граф (только верхний уровень) | `make diagrams-deps` |
| `flows/` | Sequence-диаграммы (ручные, по мере необходимости) | — |

---

## Список диаграмм по модулям

`make diagrams-per-module` создаёт для каждого модуля две PlantUML-схемы в `classes/per-module/`:

| Модуль | Файл классов | Файл пакетов |
|--------|--------------|--------------|
| actions_module | `classes_actions_module.puml` | `packages_actions_module.puml` |
| base_manager | `classes_base_manager.puml` | `packages_base_manager.puml` |
| chain_module | `classes_chain_module.puml` | `packages_chain_module.puml` |
| channel_routing_module | `classes_channel_routing_module.puml` | `packages_channel_routing_module.puml` |
| command_module | `classes_command_module.puml` | `packages_command_module.puml` |
| config_module | `classes_config_module.puml` | `packages_config_module.puml` |
| console_module | `classes_console_module.puml` | `packages_console_module.puml` |
| data_schema_module | `classes_data_schema_module.puml` | `packages_data_schema_module.puml` |
| dispatch_module | `classes_dispatch_module.puml` | `packages_dispatch_module.puml` |
| error_module | `classes_error_module.puml` | `packages_error_module.puml` |
| frontend_module | `classes_frontend_module.puml` | `packages_frontend_module.puml` |
| logger_module | `classes_logger_module.puml` | `packages_logger_module.puml` |
| message_module | `classes_message_module.puml` | `packages_message_module.puml` |
| process_manager_module | `classes_process_manager_module.puml` | `packages_process_manager_module.puml` |
| process_module | `classes_process_module.puml` | `packages_process_module.puml` |
| registers_module | `classes_registers_module.puml` | `packages_registers_module.puml` |
| router_module | `classes_router_module.puml` | `packages_router_module.puml` |
| shared_resources_module | `classes_shared_resources_module.puml` | `packages_shared_resources_module.puml` |
| sql_module | `classes_sql_module.puml` | `packages_sql_module.puml` |
| state_store_module | `classes_state_store_module.puml` | `packages_state_store_module.puml` |
| statistics_module | `classes_statistics_module.puml` | `packages_statistics_module.puml` |
| worker_module | `classes_worker_module.puml` | `packages_worker_module.puml` |

---

## Как просматривать

### `.mmd` (Mermaid)

**В VS Code:**
1. Открой `.mmd` файл
2. `Ctrl+Shift+V` или иконка "Open Preview to the Side"
3. Или: `Ctrl+Shift+P` → "Mermaid: Preview"

**Extension:** `bierner.markdown-mermaid` или `mermaidchart.vscode-mermaid-chart`

**Альтернатива:** загрузить в [mermaid.live](https://mermaid.live) — онлайн-редактор.

### `.puml` (PlantUML)

**В VS Code:**
1. Открой `.puml` файл
2. `Alt+D` — Preview Current Diagram
3. Или: правый клик → "Preview Current Diagram"

**Extension:** `jebbs.plantuml`

**Требует** в `settings.json`:
```jsonc
"plantuml.server": "https://www.plantuml.com/plantuml",
"plantuml.render": "PlantUMLServer"
```
(рендер на публичном сервере, без локальной Java)

**Альтернатива:** загрузить в [plantuml.com/plantuml](https://www.plantuml.com/plantuml) — онлайн-редактор.

### `.svg` (pydeps)

- **Браузер:** просто двойной клик в проводнике (откроется в Chrome/Edge)
- **VS Code:** правый клик → "Open With..." → "Image Preview"

---

## Регенерация

```bash
make diagrams                 # всё разом
make diagrams-classes         # UML всего фреймворка (один большой файл)
make diagrams-per-module      # UML каждого модуля отдельно
make diagrams-deps            # графы зависимостей
```

**Зависимости:**
- `pyreverse` (часть pylint) — для `.puml`
- `pydeps` + Graphviz (`dot`) — для `.svg`

Установка: `uv sync --group diagrams` + Graphviz в PATH.

---

## Workflow

1. Запустил `make diagrams` → получил актуальные схемы из кода
2. Открыл `.puml` в VS Code → увидел структуру модуля
3. Если нужно отредактировать визуально:
   - File → Import → PlantUML в Draw.io extension
   - Сохранил как `.drawio.svg` (он в git)
4. `.mmd`-диаграммы (architecture, modules-overview) правятся вручную — отражают высокоуровневое видение
