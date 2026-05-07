# Декомпозиция T1.3 — Sync framework для генерируемых разделов документации

> **Дата:** 2026-05-07
> **Статус:** DRAFT
> **Родитель:** `plans/framework_assessment_2026_05_07.md` §2 T1.3
> **ТЗ:** `plans/day1_t1_3_adr_sync.md` (полные требования — все ссылки §X.X — на этот файл)
> **Исполнители:** developer (Sonnet) для Middle/Middle+, teamlead (Opus) для Senior

---

## 1. Краткое резюме T1.3

Задача T1.3 устраняет структурную проблему: разделы «Модульные решения», «Оглавление ADR» и «Устарело» в корневом `multiprocess_framework/DECISIONS.md`, а также таблица «Коды модулей» в `docs/ADR_REGISTRY.md` — поддерживаются вручную. Это провоцирует дрифт (до 2026-05-07 — 4 пропущенных модуля и коллизия `ADR-CM`).

Решение: создать расширяемый sync-каркас `scripts/sync/` с тремя plug-in sync-модулями, маркерами `<!-- KEY:BEGIN/END -->` в md-файлах, единым CLI `python -m scripts.sync`, и подключить его к `scripts/validate.py`. После выполнения T1.3 дрифт физически невозможен: CI ловит любое расхождение.

---

## 2. Граф зависимостей задач

```
T1.3.1 (registry.py + каркас)
    └─► T1.3.2 (adr_modules.py)   ─┐
    └─► T1.3.3 (adr_toc.py)       ─┼─► T1.3.5 (ручная подготовка md-файлов)
    └─► T1.3.4 (adr_obsolete.py)  ─┘         │
                                              ▼
                                    T1.3.6 (ADR-119 + CLAUDE.md)
                                              │
                                              ▼
                                    T1.3.7 (интеграция validate.py)
                                              │
                                              ▼
                                    T1.3.8 (тесты — все файлы)
                                              │
                                              ▼
                                    T1.3.9 (финальная проверка и закрытие)
```

Задачи T1.3.2, T1.3.3, T1.3.4 — параллельны после T1.3.1.
Задача T1.3.5 — зависит от T1.3.2/3/4 (sync-модули должны быть готовы).
Задача T1.3.8 (тесты) — частично можно начинать параллельно с T1.3.5 (тесты для registry.py не зависят от md-файлов), но полный прогон — только после T1.3.5.

---

## 3. Список задач

---

### Task T1.3.1 — Каркас `scripts/sync/`: registry.py, __init__.py, __main__.py, _adr_layers.py

**Уровень:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Цель:** Создать пакет `scripts/sync/` с общим механизмом замены маркеров, Protocol `SyncModule`, функцией `apply_sync`, и CLI-точкой входа. Это фундамент, от которого зависят все три sync-модуля.

**Контекст:**
`registry.py` определяет API маркеров (`replace_between_markers`), Protocol `SyncModule`, `apply_sync(modules, check=)`. Неправильный дизайн здесь потребует переделки T1.3.2–4. `_adr_layers.py` — единственное ручное место в системе: список модулей с их слоями и порядком отображения (источник для `adr_modules`). `__main__.py` — CLI с флагами `--check`, `--only NAME`, `--list`, `--write` (по умолчанию).

**Файлы (создать):**
- `scripts/__init__.py` — пустой пакет (если не существует; нужен для `python -m scripts.sync`)
- `scripts/sync/__init__.py` — минимальный реэкспорт
- `scripts/sync/registry.py` — `SyncModule` Protocol, `MarkerNotFound`, `replace_between_markers`, `apply_sync`
- `scripts/sync/__main__.py` — CLI (argparse: `--check`, `--only`, `--list`; регистрирует три модуля)
- `scripts/sync/_adr_layers.py` — `MODULE_LAYERS: list[tuple[str, str]]` = [(module_name, layer_label), ...] в правильном порядке (21 модуль из текущей таблицы §«Модульные решения» в `DECISIONS.md`)

**Шаги:**
1. Проверить, есть ли `scripts/__init__.py`; если нет — создать пустой.
2. Создать `scripts/sync/__init__.py` (пустой или минимальный реэкспорт `apply_sync`).
3. В `scripts/sync/registry.py` реализовать:
   - `class MarkerNotFound(Exception)` с понятным сообщением (имя файла + ключ маркера).
   - `Protocol SyncModule` с полями `name: str`, `description: str` и методом `render(self) -> dict[Path, dict[str, str]]` (см. §3.2 ТЗ).
   - `def replace_between_markers(text: str, key: str, content: str) -> str` — ищет `<!-- KEY:BEGIN ... -->` и `<!-- KEY:END -->`, заменяет содержимое между ними; поднимает `MarkerNotFound` если маркеры отсутствуют.
   - `def apply_sync(modules: list[SyncModule], *, check: bool, only: str | None = None) -> int` — итерирует модули, вызывает `.render()`, применяет `replace_between_markers` к файлам; если `check=True` — не пишет файлы, а сравнивает и печатает unified diff в stderr; возвращает exit-код (0 = чисто, 1 = дрифт или ошибка).
4. В `scripts/sync/_adr_layers.py` объявить `MODULE_LAYERS` — список (module_name, layer_label) для всех 21 модулей в том же порядке, что и в текущей таблице `## Модульные решения` корневого `DECISIONS.md` (строки 1909–1930). Порядок должен воспроизводить слои: Foundation → Routing primitives → Observability → Messaging → Resources & Config → Infrastructure → Command & Work → Process → Orchestration → UI/Console → Data & SQL.
5. В `scripts/sync/__main__.py` реализовать CLI через `argparse`:
   - `--check`: передаёт `check=True` в `apply_sync`; exit 1 при дрифте.
   - `--only NAME`: передаёт имя в `apply_sync`; пропускаются модули с другим `name`.
   - `--list`: выводит список `name — description` для каждого зарегистрированного sync-модуля.
   - По умолчанию (без флагов): write-режим.
   - Регистрация (заглушки до готовности T1.3.2–4): импорт из `adr_modules`, `adr_toc`, `adr_obsolete`; `SYNC_MODULES = [adr_modules.module(), adr_toc.module(), adr_obsolete.module()]`.
   - На этапе T1.3.1 допускается, что `adr_modules`, `adr_toc`, `adr_obsolete` ещё не существуют — `__main__.py` может содержать `# TODO: uncomment after T1.3.2-4`; главное, чтобы `--list` и `apply_sync` работали с пустым списком.

**Acceptance criteria:**
- [ ] `python -m scripts.sync --list` запускается без ошибок (пустой список допустим до T1.3.2–4).
- [ ] `python -m scripts.sync --check` запускается без ошибок (exit 0 при пустом списке).
- [ ] `replace_between_markers` корректно заменяет блок между маркерами.
- [ ] `replace_between_markers` поднимает `MarkerNotFound` если маркеров нет.
- [ ] `_adr_layers.MODULE_LAYERS` содержит ровно 21 запись (по числу модулей в `DECISIONS.md`).
- [ ] `scripts/__init__.py` существует (пакет импортируем).

**Out of scope для T1.3.1:**
- Не реализовывать `adr_modules`, `adr_toc`, `adr_obsolete` — только заглушки/импорты.
- Не трогать `validate.py`.
- Не расставлять маркеры в `DECISIONS.md` / `ADR_REGISTRY.md`.

**Edge cases:**
- Маркер `BEGIN` есть, `END` нет (и наоборот) → `MarkerNotFound` с ясным сообщением «маркер KEY:END не найден в файле X».
- Файл не существует → `FileNotFoundError` с понятным сообщением.
- `replace_between_markers` должна сохранять комментарий в самом теге BEGIN: `<!-- KEY:BEGIN — generated by ... — DO NOT EDIT -->`.

**Зависимости:** нет (первая задача).

---

### Task T1.3.2 — sync-модуль `adr_modules.py`

**Уровень:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Цель:** Реализовать `scripts/sync/adr_modules.py` — sync-модуль, который сканирует локальные DECISIONS.md всех 21 модуля и генерирует таблицы «Модульные решения» и «Коды модулей».

**Контекст:**
Это самый сложный из трёх sync-модулей: содержит парсинг заголовков ADR-{CODE}-NNN, валидацию коллизий, форматирование `Статус`-столбца с 1/2/3+ ADR. Источник истины — заголовки в `modules/*/DECISIONS.md`. Порядок строк — из `_adr_layers.MODULE_LAYERS`. Два целевых раздела: в `DECISIONS.md` (ключ `ADR-INDEX`) и в `ADR_REGISTRY.md` (ключ `ADR-CODES`).

**Файлы:**
- `scripts/sync/adr_modules.py` — создать
- (опционально) `scripts/sync/tests/test_adr_modules.py` — см. T1.3.8

**Шаги:**
1. Определить dataclass `ModuleAdrs(module_name: str, code: str, layer: str, adrs: list[AdrEntry])` где `AdrEntry(num: int, title: str)`.
2. Реализовать `scan_module(decisions_path: Path) -> ModuleAdrs`:
   - Читает файл, ищет строки по regex `^## ADR-([A-Z]+)-(\d+)(?:\s+\(was ADR-[\w-]+\))?: (.+)$`.
   - Собирает уникальный `{CODE}` (если в одном файле два разных кода — `ValueError`).
   - Если заголовков нет — возвращает `ModuleAdrs` с пустым `adrs`.
3. Реализовать `validate_all(all_modules: list[ModuleAdrs]) -> None`:
   - Проверяет: один `{CODE}` на модуль, один модуль на `{CODE}` глобально.
   - Проверяет: все модули из `_adr_layers.MODULE_LAYERS` найдены в FS (и наоборот — если в FS есть модуль, которого нет в `MODULE_LAYERS`, → ошибка с подсказкой «добавь строку в `_adr_layers.py`»).
4. Реализовать `_format_status(adrs: list[AdrEntry], code: str) -> str` по правилу из §3.4 ТЗ:
   - 0 ADR: `"(нет ADR)"` или пустая строка.
   - 1 ADR: `"ADR-{CODE}-001 ({title})"`.
   - 2 ADR: `"ADR-{CODE}-001…002 ({title1}, {title2})"`.
   - 3+ ADR: `"ADR-{CODE}-001…NNN ({first_title}, ..., {last_title})"`.
5. Реализовать `render_index(all_modules: list[ModuleAdrs]) -> str` — таблица Markdown `| Модуль | Файл | Слой | Статус |` в порядке `MODULE_LAYERS`.
6. Реализовать `render_codes(all_modules: list[ModuleAdrs]) -> str` — таблица Markdown `| Код | Модуль | Файл решений |` в порядке `MODULE_LAYERS`.
7. Реализовать фабрику `module() -> SyncModule` возвращающую объект с:
   - `name = "adr_modules"`, `description = "Таблицы «Модульные решения» и «Коды модулей»"`.
   - `render()` → `{DECISIONS_MD_PATH: {"ADR-INDEX": render_index(...)}, ADR_REGISTRY_PATH: {"ADR-CODES": render_codes(...)}}`.
   - Пути вычислять относительно корня репозитория (через `Path(__file__).parent.parent.parent`).

**Acceptance criteria:**
- [ ] `adr_modules.module().render()` возвращает dict с двумя файлами и правильными ключами маркеров.
- [ ] Два модуля с одинаковым `{CODE}` → `ValueError` с понятным сообщением (тест из §6 ТЗ).
- [ ] Модуль в FS, отсутствующий в `MODULE_LAYERS` → ошибка с подсказкой.
- [ ] `render_index` детерминистичен: два последовательных вызова дают идентичный результат.
- [ ] Формат `Статус`-столбца корректен для 1, 2, 3+ ADR (тест из §6 ТЗ).
- [ ] `(was ADR-114)` суффикс в заголовке не ломает парсинг (тест из §6 ТЗ).

**Out of scope:**
- Не трогать маркеры в `DECISIONS.md` / `ADR_REGISTRY.md` — это задача T1.3.5.
- Не реализовывать `adr_toc` / `adr_obsolete`.

**Edge cases:**
- Модуль без единого заголовка ADR-{CODE}-NNN: не падать, просто пустой `adrs`.
- `frontend_module` не включён в `ADR_REGISTRY.md` (21-й модуль, статус «без DECISIONS.md» — уточнить по факту в репо).

**Зависимости:** T1.3.1 (нужны `SyncModule` Protocol, `_adr_layers`).

---

### Task T1.3.3 — sync-модуль `adr_toc.py`

**Уровень:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Цель:** Реализовать `scripts/sync/adr_toc.py` — генерирует bullet-список оглавления глобальных ADR между маркерами `<!-- ADR-TOC:BEGIN/END -->` в корневом `DECISIONS.md`.

**Контекст:**
Глобальные ADR (формат `## ADR-NNN: Title`, числовой NNN без кодового префикса) живут в теле `DECISIONS.md`. Оглавление — список ссылок, отсортированный по номеру, с пометкой `*(устарело, ...)*` для ADR, у которых `Статус: устарело`. Функция `scan_global_adrs` переиспользуется в `adr_obsolete`.

**Файлы:**
- `scripts/sync/adr_toc.py` — создать

**Шаги:**
1. Определить dataclass `GlobalAdr(num: int, title: str, is_obsolete: bool, superseded_by: str | None)`.
2. Реализовать `scan_global_adrs(decisions_path: Path) -> list[GlobalAdr]`:
   - Читает текст файла.
   - Ищет заголовки `^## ADR-(\d+): (.+)$` (только числовые, без префикса кода).
   - Для каждого ADR-блока (от заголовка до следующего `^## ADR-` или конца секции): ищет строку `^- Статус: устарело` или наличие `^- Суперсед:` → устанавливает `is_obsolete=True`.
   - Парсит `^- Суперсед:\s*\*\*ADR-(\d+)\*\*` → `superseded_by`.
3. Реализовать `render_toc(adrs: list[GlobalAdr]) -> str`:
   - Сортирует по `num`.
   - Для каждого генерирует ссылку вида `- [ADR-NNN](#adr-nnn-...): Title` (GitHub-стиль anchor: lowercase, пробелы → дефисы, без спецсимволов).
   - Устаревшие: `*(устарело, см. ADR-Y)*` или `*(устарело)*` если `superseded_by` пустой.
4. Реализовать `module() -> SyncModule` с `name="adr_toc"`, `description="Оглавление глобальных ADR в DECISIONS.md"`.

**Acceptance criteria:**
- [ ] `scan_global_adrs` находит все ADR-NNN заголовки и правильно определяет `is_obsolete`.
- [ ] TOC отсортирован по номеру (тест: перемешать входные данные — порядок в выводе всегда по возрастанию).
- [ ] ADR-099 помечен `*(устарело, см. ADR-100)*` при тестовом прогоне.
- [ ] Добавление нового `## ADR-119: Foo` в тело документа → diff виден при `--check`.

**Out of scope:**
- Не трогать маркеры в `DECISIONS.md` — это T1.3.5.
- Не генерировать ссылки на модульные ADR (`ADR-CHN-001` и т.д.) — только числовые.

**Edge cases:**
- ADR без тела (следующий заголовок сразу после) — `is_obsolete=False`, `superseded_by=None`.
- Строка `Статус: принято (частично устарело по схемам регистров)` (ADR-025 в тексте) — не считать за `устарело` (только точная строка `Статус: устарело`).

**Зависимости:** T1.3.1 (`SyncModule` Protocol).

---

### Task T1.3.4 — sync-модуль `adr_obsolete.py`

**Уровень:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Цель:** Реализовать `scripts/sync/adr_obsolete.py` — генерирует список ссылок-заголовков для раздела «Устарело» между маркерами `<!-- ADR-OBSOLETE:BEGIN/END -->`.

**Контекст:**
Переиспользует `scan_global_adrs` из `adr_toc`. Фильтрует только `is_obsolete=True`. Генерирует **только ссылки**, не полные тела ADR. Полные тела остаются в основном блоке документа (перед разделом «Устарело»).

**Файлы:**
- `scripts/sync/adr_obsolete.py` — создать

**Шаги:**
1. Импортировать `scan_global_adrs, GlobalAdr` из `adr_toc`.
2. Реализовать `render_obsolete(adrs: list[GlobalAdr]) -> str`:
   - Фильтрует `adrs` по `is_obsolete=True`.
   - Для каждого генерирует строку: `- **ADR-NNN**: Title *(Суперсед: **ADR-Y**, YYYY-MM-DD)*` если `superseded_by` известен.
   - Если `superseded_by` неизвестен: `- **ADR-NNN**: Title *(устарело)*`.
   - Если дат суперседа нет в `GlobalAdr` — `Суперсед: **ADR-Y**` без даты (дата — опциональное улучшение, не блокирует).
3. Реализовать `module() -> SyncModule` с `name="adr_obsolete"`, `description="Раздел «Устарело» в DECISIONS.md (только ссылки)"`.

**Acceptance criteria:**
- [ ] ADR с `Статус: устарело` попадает в вывод.
- [ ] ADR без `Статус: устарело` — не попадает.
- [ ] `Суперсед: ADR-100` парсится и отображается в выводе.
- [ ] `render_obsolete` не содержит полных тел ADR — только однострочные ссылки.

**Out of scope:**
- Не трогать маркеры в `DECISIONS.md` — это T1.3.5.
- Не парсировать дату суперседа — только номер.
- Не определять самостоятельно паттерн `scan_global_adrs` — переиспользовать из `adr_toc`.

**Edge cases:**
- Если устаревших ADR нет — `render_obsolete` возвращает пустую строку (не ломать `replace_between_markers`).

**Зависимости:** T1.3.1 (`SyncModule` Protocol), T1.3.3 (`scan_global_adrs`, `GlobalAdr`).

---

### Task T1.3.5 — Ручная подготовка md-файлов: расстановка маркеров и чистка дубля ADR-099

**Уровень:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Цель:** Обернуть существующие разделы маркерами `<!-- KEY:BEGIN/END -->` в двух файлах и удалить дубль тела `ADR-099` из раздела «Устарело».

**Контекст:**
`replace_between_markers` (из `registry.py`) требует, чтобы маркеры уже присутствовали в файле. Расстановка — разовая ручная работа. Важно: генератор должен увидеть нулевой (или косметический) diff после `--write` — это подтверждает корректность алгоритмов T1.3.2–4. Дубль ADR-099 описан в §3.4 и §7.3 ТЗ.

**Файлы (изменить):**
- `multiprocess_framework/DECISIONS.md` — три маркера: `ADR-TOC`, `ADR-INDEX`, `ADR-OBSOLETE`
- `multiprocess_framework/docs/ADR_REGISTRY.md` — один маркер: `ADR-CODES`

**Шаги:**
1. В `DECISIONS.md` найти раздел «Оглавление (по номеру)» (строки ~20–137). Обернуть содержимое (список bullet-ссылок) в:
   ```
   <!-- ADR-TOC:BEGIN — generated by scripts/sync/adr_toc.py — DO NOT EDIT -->
   ...существующий список...
   <!-- ADR-TOC:END -->
   ```
   Маркер должен охватывать только тело списка, не заголовок `## Оглавление (по номеру)`.
2. В `DECISIONS.md` найти раздел «Модульные решения» (строки ~1905–1931). Обернуть таблицу модулей в:
   ```
   <!-- ADR-INDEX:BEGIN — generated by scripts/sync/adr_modules.py — DO NOT EDIT -->
   ...существующая таблица...
   <!-- ADR-INDEX:END -->
   ```
   Маркер должен охватывать только тело таблицы (включая заголовок таблицы `| Модуль | Файл | Слой | Статус |`), не заголовок раздела `## Модульные решения`.
3. В `DECISIONS.md` найти раздел «Устарело» (строки ~1934–1946). Убедиться, что тело `ADR-099` уже есть в основной части документа (в разделе «Принято» или основном теле) — да, оно есть (ADR-099 есть в TOC и в основном блоке ADR-099 перед «Устарело»). Удалить из раздела «Устарело» полное тело (`## ADR-099: ...` со всеми полями). Оставить только вводный абзац («Ниже — решения, явно помеченные...»). Обернуть в маркеры:
   ```
   <!-- ADR-OBSOLETE:BEGIN — generated by scripts/sync/adr_obsolete.py — DO NOT EDIT -->
   <!-- ADR-OBSOLETE:END -->
   ```
4. В `ADR_REGISTRY.md` найти раздел «Коды модулей» (таблица `| Код | Модуль | Файл решений |`, строки ~16–38). Обернуть таблицу в:
   ```
   <!-- ADR-CODES:BEGIN — generated by scripts/sync/adr_modules.py — DO NOT EDIT -->
   ...существующая таблица...
   <!-- ADR-CODES:END -->
   ```
5. Запустить `python -m scripts.sync` (write-режим). Убедиться, что diff минимальный (только автоматический формат статуса заменяет ручные описания — это ожидаемо, см. §7.1 ТЗ).
6. Запустить `python -m scripts.sync --check` — должен вернуть exit 0.

**Acceptance criteria:**
- [ ] В `DECISIONS.md` присутствуют три пары маркеров: `ADR-TOC`, `ADR-INDEX`, `ADR-OBSOLETE`.
- [ ] В `ADR_REGISTRY.md` присутствует пара маркеров `ADR-CODES`.
- [ ] Дубль полного тела `ADR-099` из раздела «Устарело» удалён; полное тело ADR-099 сохранено в основном блоке документа.
- [ ] `python -m scripts.sync --check` завершается exit 0 (нулевой дрифт после `--write`).

**Out of scope:**
- Не удалять вводный абзац раздела «Устарело».
- Не трогать структуру маппинга старых → новых номеров в `ADR_REGISTRY.md` (только таблицу кодов модулей).
- Не переписывать содержимое таблиц вручную — генератор сделает это сам.

**Edge cases:**
- Если после `--write` diff ненулевой, но косметический (изменение формата «Статус»-столбца) — это ожидаемо (§7.1 ТЗ). Нужно зафиксировать результат `--write` как новое состояние, затем `--check` должен дать exit 0.

**Зависимости:** T1.3.2, T1.3.3, T1.3.4 (все три sync-модуля должны быть реализованы).

---

### Task T1.3.6 — ADR-119 в DECISIONS.md и правило в CLAUDE.md

**Уровень:** Junior (Haiku, normal)
**Assignee:** docs-writer
**Цель:** Добавить `ADR-119` в корневой `DECISIONS.md` и пункт 8 в корневой `CLAUDE.md`.

**Контекст:**
ADR-119 фиксирует архитектурное решение о sync-каркасе (см. §3.5 ТЗ). После добавления ADR-119 в тело документа — `adr_toc` автоматически включит его в TOC при следующем `--write`. Правило в `CLAUDE.md` (§3.6 ТЗ) информирует агентов о необходимости запуска `python -m scripts.sync` после правок документации.

**Файлы (изменить):**
- `multiprocess_framework/DECISIONS.md` — добавить тело ADR-119 **перед** разделом «Модульные решения»
- `CLAUDE.md` (корневой) — добавить пункт 8 в §«Правила проекта»

**Шаги:**
1. В `DECISIONS.md` после последнего ADR-118 (строка ~1902) вставить блок:
   ```markdown
   ## ADR-119: Sync framework для генерируемых разделов документации
   - Дата: 2026-05-07
   - Статус: принято
   - Контекст: [см. §3.5 ТЗ day1_t1_3_adr_sync.md]
   - Решение: [см. §3.5 ТЗ]
   - Причина: [см. §3.5 ТЗ]
   - Отклонённые альтернативы: [см. §3.5 ТЗ]
   ```
   Содержимое полей — из §3.5 ТЗ (контекст, решение, причина, отклонённые альтернативы).
2. В `CLAUDE.md` в раздел «Правила проекта» добавить пункт 8:
   ```markdown
   8. **Документация — auto-sync:** после правок `multiprocess_framework/DECISIONS.md` или `modules/*/DECISIONS.md` — `python -m scripts.sync`. CI ловит дрифт через `python scripts/validate.py`. Что синхронизируется: `python -m scripts.sync --list`.
   ```
3. Запустить `python -m scripts.sync` (write) — ADR-119 должен появиться в TOC автоматически.
4. Запустить `python -m scripts.sync --check` — exit 0.

**Acceptance criteria:**
- [ ] `ADR-119` присутствует в теле `DECISIONS.md` с полями Дата/Статус/Контекст/Решение/Причина/Отклонённые альтернативы.
- [ ] Правило 8 добавлено в `CLAUDE.md` §«Правила проекта».
- [ ] После `--write` ADR-119 появляется в разделе TOC автоматически.

**Out of scope:**
- Не трогать `validate.py` — это T1.3.7.
- Не менять маркеры в md-файлах — уже расставлены в T1.3.5.

**Зависимости:** T1.3.5 (маркеры должны быть расставлены, `--write` работает).

---

### Task T1.3.7 — Интеграция `scripts/validate.py`

**Уровень:** Junior (Haiku, normal)
**Assignee:** docs-writer
**Цель:** Добавить вызов `python -m scripts.sync --check` в `scripts/validate.py` как шестую проверку.

**Контекст:**
`validate.py` уже содержит 5 проверок (импорты, sys.path, __init__.py, interfaces.py, STATUS.md). Нужно добавить шестую — запуск sync --check через `subprocess.run` (предпочтительнее прямого импорта, см. §7.4 ТЗ: избегаем sys.path-хакинга). Падение sync --check должно добавлять ошибку в список `errors[]` и менять exit-код на 1.

**Файлы (изменить):**
- `scripts/validate.py`

**Шаги:**
1. Добавить импорт `import subprocess` в начало файла.
2. Добавить функцию `check_adr_sync() -> None`:
   ```python
   def check_adr_sync() -> None:
       check_header("6. Проверка синхронизации ADR-документации (scripts/sync --check)")
       result = subprocess.run(
           [sys.executable, "-m", "scripts.sync", "--check"],
           capture_output=True, text=True, cwd=str(BASE)
       )
       if result.returncode == 0:
           print("  [OK] ADR-документация синхронизирована")
       else:
           msg = "  [FAIL] ADR дрифт обнаружен — запусти: python -m scripts.sync"
           print(msg)
           if result.stderr:
               print(result.stderr)
           errors.append(msg)
   ```
3. Добавить вызов `check_adr_sync()` в функцию `main()` после `check_status_files()`.

**Acceptance criteria:**
- [ ] `python scripts/validate.py` содержит раздел «6. Проверка синхронизации ADR-документации».
- [ ] При нулевом дрифте — `[OK]`, exit 0.
- [ ] При дрифте — `[FAIL]` + unified diff в stderr, exit 1.
- [ ] Вызов через `subprocess.run` с `cwd=str(BASE)` (не через прямой импорт).

**Out of scope:**
- Не менять существующие 5 проверок.
- Не добавлять флаги (validate.py запускается без аргументов).

**Edge cases:**
- `scripts/sync/` не установлен → `subprocess.run` вернёт ненулевой код с понятным сообщением Python (ModuleNotFoundError) → добавится в errors с raw stderr.

**Зависимости:** T1.3.1 (пакет `scripts.sync` должен существовать и запускаться).

---

### Task T1.3.8 — Тесты: `scripts/sync/tests/`

**Уровень:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Цель:** Написать полный набор pytest-тестов для каркаса и всех трёх sync-модулей, используя `tmp_path` и изолированные fixtures.

**Контекст:**
Тесты полностью изолированы — не трогают реальные `DECISIONS.md` репо. Все fixtures создают временные файлы с минимальным валидным содержимым. Полный список сценариев — §6 ТЗ. Важно: тесты для `adr_modules` зависят от `_adr_layers.MODULE_LAYERS` — если в тестовых fixtures использовать реальные имена модулей, нужно либо мокать `MODULE_LAYERS`, либо создавать временный файл с известным содержимым.

**Файлы (создать):**
- `scripts/sync/tests/__init__.py`
- `scripts/sync/tests/test_registry.py`
- `scripts/sync/tests/test_adr_modules.py`
- `scripts/sync/tests/test_adr_toc.py`
- `scripts/sync/tests/test_adr_obsolete.py`
- `scripts/sync/tests/test_cli.py`

**Шаги:**
1. `test_registry.py` (3 сценария из §6 ТЗ):
   - `test_replace_between_markers_ok` — создаёт текст с маркерами, проверяет замену содержимого.
   - `test_marker_not_found` — текст без маркеров → `MarkerNotFound`.
   - `test_check_mode_diff` — создаёт sync-модуль-заглушку, применяет через `apply_sync(check=True)`, проверяет exit 1 при дрифте.

2. `test_adr_modules.py` (5 сценариев из §6 ТЗ):
   - `test_scan_with_was_suffix` — файл с `## ADR-CHN-001 (was ADR-114): Title` → корректный `AdrEntry`.
   - `test_detect_duplicate_code` — два модуля с одинаковым кодом → ошибка.
   - `test_detect_missing_in_layers` — модуль есть в FS, нет в `MODULE_LAYERS` (мокнуть) → ошибка с подсказкой.
   - `test_render_index_deterministic` — два вызова `render_index` с одним входом → идентичный вывод.
   - `test_format_status_variants` — parametrize: 1, 2, 3+ ADR → ожидаемый формат строки.

3. `test_adr_toc.py` (3 сценария из §6 ТЗ):
   - `test_scan_with_obsolete` — текст с `Статус: устарело` → `is_obsolete=True`.
   - `test_sort_by_number` — перемешанные ADR → вывод отсортирован.
   - `test_drift_on_new_adr` — добавить `## ADR-119: Foo` в fixtures-файл → `apply_sync(check=True)` возвращает exit 1.

4. `test_adr_obsolete.py` (2 сценария из §6 ТЗ):
   - `test_obsolete_included` — ADR с `Статус: устарело` → в выводе `render_obsolete`.
   - `test_superseded_parsed` — `Суперсед: **ADR-100**` → в выводе `*(Суперсед: **ADR-100**)*`.

5. `test_cli.py` (4 сценария из §6 ТЗ):
   - `test_list_shows_three_modules` — `--list` выводит три строки с именами sync-модулей.
   - `test_only_flag_isolates` — `--only adr_toc` не вызывает `render()` других модулей (мокнуть render).
   - `test_check_after_write_exit0` — `--write` + `--check` → exit 0 (идемпотентность).
   - `test_check_after_manual_edit_exit1` — после `--write` ручная правка между маркерами → `--check` exit 1.

**Acceptance criteria:**
- [ ] `pytest scripts/sync/tests/` — green (0 failures, 0 errors).
- [ ] Все тесты используют `tmp_path` — нет обращений к реальным файлам репо.
- [ ] Покрыты все 17 сценариев из §6 ТЗ.
- [ ] Тесты не требуют реального `DECISIONS.md` или реальных модульных DECISIONS.md.

**Out of scope:**
- Не писать e2e-тест по реальному репо (это делается в T1.3.9).
- Не тестировать `validate.py` интеграционно — только unit.

**Edge cases:**
- `test_detect_missing_in_layers`: нужно мокнуть `_adr_layers.MODULE_LAYERS` или параметризовать функции scan — убедиться что это возможно без monkey-patching globals.

**Зависимости:** T1.3.1, T1.3.2, T1.3.3, T1.3.4 (все модули должны быть реализованы для написания корректных тестов).

---

### Task T1.3.9 — Финальная проверка и закрытие T1.3

**Уровень:** Junior (Haiku, normal)
**Assignee:** docs-writer
**Цель:** Прогнать `validate.py` и `run_framework_tests.py`, убедиться в green-статусе, обновить статус в планах.

**Контекст:**
Финальная задача, подтверждающая что вся T1.3 выполнена. Не требует написания кода — только запуск и обновление двух markdown-файлов.

**Файлы (изменить):**
- `multiprocess_framework/IMPROVEMENT_PLAN.md` — T1.3 → ✅
- `plans/framework_assessment_2026_05_07.md` § «История обновлений» — добавить запись

**Шаги:**
1. Запустить `python -m scripts.sync --check` → убедиться exit 0.
2. Запустить `python -m scripts.sync --list` → убедиться что три модуля.
3. Запустить `python scripts/validate.py` → убедиться green.
4. Запустить `pytest scripts/sync/tests/` → убедиться green.
5. В `IMPROVEMENT_PLAN.md` найти T1.3 и пометить ✅.
6. В `plans/framework_assessment_2026_05_07.md` добавить строку:
   ```
   | 2026-05-07 | T1.3 закрыт. `scripts/sync/` создан (3 sync-модуля). ADR-119 добавлен. `validate.py` подключён. |
   ```

**Acceptance criteria:**
- [ ] `python -m scripts.sync --check` → exit 0.
- [ ] `python -m scripts.sync --list` → три модуля.
- [ ] `python scripts/validate.py` → green.
- [ ] `pytest scripts/sync/tests/` → green.
- [ ] `IMPROVEMENT_PLAN.md` содержит ✅ для T1.3.
- [ ] `framework_assessment_2026_05_07.md` обновлён.

**Out of scope:**
- Не писать новый код.
- Не исправлять ошибки — если что-то красное, возвращаться к соответствующей задаче.

**Зависимости:** T1.3.6, T1.3.7, T1.3.8 (все предыдущие задачи завершены).

---

## 4. Definition of Done — T1.3 (копия §9 ТЗ)

- [ ] PR содержит: `scripts/sync/` пакет (5 файлов + `tests/`), маркированные `DECISIONS.md` и `ADR_REGISTRY.md`, `ADR-119`, правило в `CLAUDE.md`, правки `validate.py`.
- [ ] `python -m scripts.sync --check` — exit 0.
- [ ] `python -m scripts.sync --list` — три модуля.
- [ ] `python scripts/validate.py` — green.
- [ ] `pytest scripts/sync/tests/` — green.
- [ ] reviewer-агент апрувит без второй итерации.
- [ ] Запись в `framework_assessment_2026_05_07.md` § «История обновлений»: T1.3 закрыт, ADR-119 добавлен.

---

## 5. Резолюции по открытым вопросам (зафиксированы Director)

### 5.1. `frontend_module` — не имеет локального ADR-кода

**Факт:** `multiprocess_framework/modules/frontend_module/DECISIONS.md` существует, но это **индекс ссылок** на глобальные `ADR-033..097`. Локальных `ADR-FE-NNN` или иных нет.

**Решение:**
- В `_adr_layers.py` объявить **две** константы:
  - `MODULE_LAYERS: list[tuple[str, str]]` — 20 модулей с локальными ADR-кодами, в порядке слоёв.
  - `MODULES_WITHOUT_LOCAL_ADR: set[str] = {"frontend_module"}` — модули, намеренно не имеющие локального кода (читают глобальные).
- В `validate_all` (T1.3.2): каждый модуль из FS должен быть либо в `MODULE_LAYERS`, либо в `MODULES_WITHOUT_LOCAL_ADR`. Иначе ошибка с подсказкой «добавь в один из двух списков `_adr_layers.py`».
- В `render_index` / `render_codes` (T1.3.2): итерируем только по `MODULE_LAYERS`. `frontend_module` в таблицах не появляется (как и в текущем ручном состоянии).

### 5.2. `scripts/__init__.py` отсутствует

**Факт:** проверено — файл не существует.

**Решение:** T1.3.1 создаёт пустой `scripts/__init__.py`. Без него `python -m scripts.sync` не найдёт пакет.

### 5.3. Стратегия мокирования `MODULE_LAYERS` в тестах — параметризация функций

**Решение:** функции `validate_all`, `render_index`, `render_codes` в `adr_modules.py` принимают `module_layers: list[tuple[str, str]]` и `modules_without_local_adr: set[str]` как **параметры** (default — глобальные `_adr_layers.MODULE_LAYERS` и `MODULES_WITHOUT_LOCAL_ADR`). Тесты передают свои значения через kwargs. Чище чем `monkeypatch` модуль-глобалов.

API:
```python
def validate_all(
    all_modules: list[ModuleAdrs],
    *,
    module_layers: list[tuple[str, str]] | None = None,
    modules_without_local_adr: set[str] | None = None,
) -> None: ...

def render_index(
    all_modules: list[ModuleAdrs],
    *,
    module_layers: list[tuple[str, str]] | None = None,
) -> str: ...
```
Если `None` — используются дефолты из `_adr_layers`.

---

## 6. Распределение исполнителей (утверждено Director)

| Task | Уровень | Исполнитель |
|------|---------|-------------|
| T1.3.1 — registry + каркас | Senior | **teamlead** (Opus) |
| T1.3.2 — adr_modules | Middle+ | **developer** (Sonnet) |
| T1.3.3 — adr_toc | Middle | **developer** (Sonnet) |
| T1.3.4 — adr_obsolete | Middle | **developer** (Sonnet) |
| T1.3.5 — маркеры в md + чистка ADR-099 | Middle | **developer** (Sonnet) |
| T1.3.6 — ADR-119 + правило в CLAUDE.md | Junior+ архитектура | **tech-writer** (Sonnet) |
| T1.3.7 — интеграция validate.py | Junior (код) | **developer** (Sonnet) |
| T1.3.8 — тесты | Middle | **tester** (Sonnet) |
| T1.3.9 — финальная проверка + статусы | Junior | **docs-writer** (Haiku) |
