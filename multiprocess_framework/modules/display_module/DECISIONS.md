# DECISIONS — display_module

Локальные архитектурные решения модуля `display_module`.
Глобальный ADR (DisplayRegistry в контексте фреймворка) — ADR-130 в [`multiprocess_framework/DECISIONS.md`](../../DECISIONS.md) (Task 4.9).

---

## ADR-DM-001: DisplayEntry generic: без vision-полей

**Дата:** 2026-05-25
**Статус:** Принято
**Task context:** Task 4.1 — interfaces.py

### Контекст

Framework должен оставаться generic — пригодным для любого приложения, не только для computer vision. Поля image-specific семантики (`element_shape`, `dtype` для numpy-массивов) явно привязывают `DisplayEntry` к numpy/OpenCV и делают framework зависимым от конкретного ML-стека. Кроме того, `element_shape` является производным от `width`, `height` и `format` — хранить производное значение в источнике истины излишне.

### Альтернативы

**A. Включить `element_shape: tuple[int,...]` и `dtype: str` в `DisplayEntry`**
- Плюсы: вызывающий не вычисляет shape самостоятельно; blueprint-binding тривиален
- Минусы: framework получает зависимость на numpy-семантику; нарушает принцип generic-first; приложения без image-frames (audio, lidar) вынуждены заполнять поля-заглушки; `element_shape` — производное от `(height, width, channels)`, дублирование данных

**B. Хранить только generic-параметры; vision-конвертацию делает prototype-слой**
- Плюсы: framework переиспользуется для не-vision SHM (audio-буфер, lidar point cloud); `_format_to_channels("BGR") → 3` — пять строк в prototype, не в framework; нет зависимости от numpy в framework
- Минусы: каждое приложение должно иметь свою обёртку для конвертации `format → channels`

**C. Два класса: `DisplayEntry` (generic) + `ImageDisplayEntry(DisplayEntry)` в prototype**
- Плюсы: явная иерархия типов
- Минусы: избыточная сложность; `DisplayRegistry` перестаёт быть typed (хранит `DisplayEntry | ImageDisplayEntry`); blueprint-binding всё равно идёт в prototype

### Решение

Выбран вариант B. `DisplayEntry` содержит только generic-параметры: `id`, `name`, `width`, `height`, `format`, `fps_limit`, `ring_buffer_blocks`. Vision-семантика (`element_shape`, `dtype`) живёт в prototype-обёртке (`backend/displays/blueprint_binding.py` через `_format_to_channels`).

### Последствия

- Framework переиспользуется для не-vision SHM (audio, lidar)
- Каждое приложение реализует `format → channels` самостоятельно (пять строк)
- Нет зависимости от numpy в `multiprocess_framework/`
- `element_shape` вычисляется один раз при bind (не хранится, не дрейфует)

---

## ADR-DM-002: `persist(path)` принимает path аргументом

**Дата:** 2026-05-25
**Статус:** Принято
**Task context:** Task 4.2 — registry.py

### Контекст

Singleton-реестр в framework не должен знать application-specific пути. Путь `multiprocess_prototype/backend/config/displays.yaml` — деталь конкретного приложения, не фреймворка. Если путь «зашить» в `DisplayRegistry`, то при смене структуры директорий prototype-слоя — нужно менять framework (нарушение слоёв). Кроме того, разные тесты могут захотеть persist в разные временные файлы.

### Альтернативы

**A. Хранить путь в конструкторе `DisplayRegistry(path=...)`**
- Плюсы: `reg.persist()` без аргументов
- Минусы: singleton не может иметь разные пути в разных контекстах; тест-изоляция усложнена; YAML-путь попадает в framework-слой

**B. Константа-путь как атрибут класса (override через подкласс)**
- Плюсы: нет аргумента
- Минусы: inheritance для конфига — антипаттерн; ещё сложнее в тестах; нарушает OCP

**C. `persist(path: Path)` — явный аргумент (вызывающий несёт ответственность)**
- Плюсы: prototype решает, куда сохранять; тесты используют `tmp_path`; framework не знает о prototype-файловой структуре; совместимо с ADR-025 (config-driven memory); вызывающий явно контролирует консистентность пути
- Минусы: вызывающий код должен хранить путь (обычно — константа в bootstrap или presenter)

### Решение

Выбран вариант C. `DisplayRegistry.persist(path: Path)` и `DisplayRegistry.load(path: Path)` принимают явный аргумент. Prototype-слой (`DisplaysTab`, `bootstrap.py`) несёт ответственность за передачу правильного пути.

### Последствия

- Framework не имеет ни одного упоминания путей к файлам prototype
- Совместимо с ADR-025 (config-driven memory): вся конфигурация инициируется из prototype-слоя
- Тесты используют `tmp_path` (pytest) — изоляция бесплатна
- Вызывающий код обеспечивает консистентность пути между `persist` и `load` (одна константа в `AppConfig` или `bootstrap.py`)

---

## ADR-DM-003: SHM cleanup при unregister — только warning

**Дата:** 2026-05-25
**Статус:** Принято
**Task context:** Task 4.2 — registry.py

### Контекст

При удалении дисплея из реестра (`unregister`) возникает вопрос: нужно ли немедленно освобождать SHM-сегмент? Прямой cleanup из `display_module` потребовал бы импорта `shared_resources_module` (для доступа к `SharedResourcesManager`) или `router_module` (для `unregister_channel`). Это создаёт жёсткую связь между тремя независимыми модулями framework и нарушает принцип единой ответственности: `display_module` — реестр конфигурации, не менеджер SHM-ресурсов.

### Альтернативы

**A. Импортировать `shared_resources_module` из `display_module` и вызвать cleanup**
- Плюсы: немедленное освобождение памяти
- Минусы: жёсткая связь `display_module → shared_resources_module`; нарушает слои (оба на уровне framework, но с разными зонами ответственности); `shared_resources_module` может быть недоступен вне process-контекста (GUI-процесс vs worker-процесс)

**B. Callback-механизм: вызывающий передаёт `on_unregister: Callable`**
- Плюсы: decoupling через callback
- Минусы: усложняет API singleton'а; кто передаёт callback при импорте через `@register`-паттерн?; тесты усложняются

**C. Только лог-предупреждение; фактический cleanup при рестарте `ProcessManagerProcess`**
- Плюсы: нет зависимости `display_module → shared_resources_module`; `ProcessManagerProcess` и так пересоздаёт SHM-сегменты по blueprint при каждом старте — отсутствие entry → SHM не создаётся; явное предупреждение в логе сигнализирует оператору
- Минусы: возможна короткая зомби-память SHM до рестарта; лог-предупреждение тихое, если logger не передан в `DisplayRegistry(logger=...)`

### Решение

Выбран вариант C. `_cleanup_shm_channel(display_id)` логирует предупреждение с явным указанием на ADR-025 / ADR-DM-003. Фактическое освобождение — ответственность `ProcessManagerProcess` при следующем рестарте (отсутствие entry в blueprint → SHM не создаётся). Trade-off в пользу decoupling: кратковременная зомби-память приемлема в сценарии, где рестарт процессов — нормальная операция.

### Последствия

- `display_module` не импортирует `shared_resources_module` или `router_module`
- Возможна кратковременная зомби-память SHM (до следующего рестарта процессов)
- Logger-fallback (`DisplayRegistry(logger=...)`) позволяет отображать предупреждение в GUI-логе при необходимости; если logger не передан — предупреждение silent
- Принцип decoupling между независимыми framework-модулями сохранён

---

## ADR-DM-004: `reload` = только метаданные, render-поля игнорируются

**Дата:** 2026-06-07
**Статус:** Принято
**Task context:** Task 2.1 — DisplayRegistry.reload (план displays-in-recipe)

### Контекст

При переключении рецепта `DisplayRegistry` нужно атомарно перезаполнить определениями нового рецепта. Определения на границе процесса приходят как `list[dict]` и содержат как SHM-поля (`id/name/width/height/format/fps_limit/ring_buffer_blocks`), так и render-поля (`fit/scale/rotate/flip/crop/position`). Вопрос: что должен хранить реестр?

### Альтернативы

**A. Расширить `DisplayEntry` render-полями и хранить всё в реестре**
- Плюсы: один источник истины для всех данных дисплея
- Минусы: нарушает ADR-DM-001 (generic); framework получает знание о render-pipeline; не-vision приложения обязаны заполнять render-заглушки; blueprint_binding усложняется

**B. `reload` фильтрует: берёт только SHM-поля, render-поля игнорирует**
- Плюсы: сохраняет ADR-DM-001; реестр остаётся generic; render живёт в prototype-слое (`DisplayDefinition`, `DisplaySpec`, `PreviewWindow`); минимальные изменения framework; SHM-аллокация не затронута (реестр SHM не владеет — ADR-DM-003)
- Минусы: render-параметры нужно доставлять в prototype отдельным каналом (но это и так через domain entity `DisplayDefinition`)

**C. Два реестра: SHM-реестр (framework) + render-реестр (prototype)**
- Плюсы: явное разделение
- Минусы: избыточная сложность; sync двух реестров; один dict на границе всё равно содержит оба набора полей

### Решение

Выбран вариант B. `DisplayRegistry.reload(entries)` принимает `list[dict]` и извлекает ТОЛЬКО 7 SHM-ключей (`id`, `name`, `width`, `height`, `format`, `fps_limit`, `ring_buffer_blocks`). Все остальные ключи (render, prototype-specific) тихо игнорируются. SHM реестром не выделяется и не освобождается — `_cleanup_shm_channel` остаётся лог-предупреждением (ADR-DM-003). Render-параметры доступны prototype-слою через `DisplayDefinition` (domain entity) и `DisplaySpec` (adapter).

Идемпотентность гарантирована: `reload(same)` = тот же реестр; `reload(old)` после `reload(new)` полностью восстанавливает предыдущий набор — достаточно для rollback в `apply_topology` (Архитектурное решение №2 плана).

### Последствия

- `DisplayEntry` и `DisplayRegistry` остаются generic (ADR-DM-001 сохранён)
- Framework не знает о render-pipeline — SoC между слоями соблюдён
- `bind_displays_to_blueprint` — obsolete (мёртвый код), не воскрешается
- Rollback = повторный `reload(old_defs)` — дешёвая операция без SHM side-effects
- Prototype получает render-параметры через domain entity, не через реестр

---

## Индекс ADR

| ID | Название | Статус | Task |
|----|----------|--------|------|
| ADR-DM-001 | DisplayEntry generic: без vision-полей | Принято | 4.1 |
| ADR-DM-002 | `persist(path)` принимает path аргументом | Принято | 4.2 |
| ADR-DM-003 | SHM cleanup при unregister — только warning | Принято | 4.2 |
| ADR-DM-004 | `reload` = только метаданные, render-поля игнорируются | Принято | 2.1 (displays-in-recipe) |
