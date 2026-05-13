# Plan: Консолидация MCP-инфраструктуры в `.claude/mcp/`

- **Slug:** mcp-consolidation
- **Дата:** 2026-05-13
- **Статус:** DRAFT
- **Ветка:** (заполняется Director после создания)

## Обзор

Собрать всю MCP-документацию (qex, sentrux) из разрозненных мест (`docs/claude/qex/`, `docs/claude/sentrux/`) в единый портативный каталог `.claude/mcp/`. Создать шаблон sentrux-правил и инструкцию переноса в новый проект (`PORTABLE.md`). Обновить все ссылки в `CLAUDE.md` и внутренних документах.

**Проектоспецифичные файлы остаются на месте:** `.mcp.json` (корень), `.sentrux/rules.toml` + `baseline.json` (корень).

## Текущее состояние

| Источник | Файлы | Статус |
|----------|-------|--------|
| `.claude/mcp/` | `README.md`, `bootstrap.py`, `qex-launcher.py`, `mcp.template.json` | Уже на месте |
| `docs/claude/qex/` | `README.md`, `SETUP_GUIDE.md`, `templates/` (3 файла) | Переносить |
| `docs/claude/sentrux/` | `README.md` | Переносить |
| `.sentrux/` | `rules.toml`, `baseline.json` | Остаётся (проектоспецифичное) |
| `scripts/hooks/pre-push` | hook с sentrux check/gate | Остаётся (проектоспецифичное) |

## Целевая структура

```
.claude/mcp/
├── README.md                  # обновить как master guide (ссылки на подпапки)
├── bootstrap.py               # обновить (путь к rules.template.toml)
├── qex-launcher.py            # без изменений
├── mcp.template.json          # без изменений
├── sentrux/
│   ├── README.md              # из docs/claude/sentrux/README.md (обновить внутренние ссылки)
│   └── rules.template.toml   # НОВЫЙ: универсальный шаблон правил
├── qex/
│   ├── README.md              # из docs/claude/qex/README.md (обновить ссылки)
│   ├── SETUP_GUIDE.md         # из docs/claude/qex/SETUP_GUIDE.md
│   └── templates/
│       ├── ignore.template
│       ├── post-commit.hook.sh
│       └── mcp-config.json.snippet
└── PORTABLE.md                # НОВЫЙ: инструкция "как скопировать в новый проект"
```

## Ссылки, требующие обновления

| Файл | Строки | Что менять |
|------|--------|-----------|
| `CLAUDE.md` | 34 | `docs/claude/qex/README.md` → `.claude/mcp/qex/README.md` |
| `CLAUDE.md` | 34 | `docs/claude/qex/SETUP_GUIDE.md` → `.claude/mcp/qex/SETUP_GUIDE.md` |
| `CLAUDE.md` | 35, 150 | `docs/claude/sentrux/README.md` → `.claude/mcp/sentrux/README.md` |
| `docs/claude/sentrux/README.md` (после переноса) | 279 | Ссылка `../../../CLAUDE.md` → `../../../CLAUDE.md` (глубина не меняется, `.claude/mcp/sentrux/` = 3 уровня) |
| `docs/claude/qex/README.md` (после переноса) | 94-101 | Обновить блок «Структура папки» |
| `.claude/mcp/README.md` | — | Добавить ссылки на подпапки `qex/`, `sentrux/`, `PORTABLE.md` |

## Порядок выполнения

### Phase 1: Перенос документации и создание новых файлов

- Task 1.1: Перенос qex-документации [PENDING]
- Task 1.2: Перенос sentrux-документации [PENDING]
- Task 1.3: Создание `rules.template.toml` [PENDING]
- Task 1.4: Создание `PORTABLE.md` [PENDING]

### Phase 2: Обновление ссылок и интеграция

- Task 2.1: Обновление `CLAUDE.md` [PENDING] (зависит от 1.1, 1.2)
- Task 2.2: Обновление `.claude/mcp/README.md` [PENDING] (зависит от 1.1, 1.2, 1.3, 1.4)
- Task 2.3: Обновление `bootstrap.py` [PENDING] (зависит от 1.3)

### Phase 3: Очистка старых путей

- Task 3.1: Удаление `docs/claude/qex/` и `docs/claude/sentrux/` [PENDING] (зависит от 2.1, 2.2)

---

## Детальные спецификации задач

---

### Task 1.1 — Перенос qex-документации в `.claude/mcp/qex/`

**Level:** Junior (Haiku)
**Assignee:** developer
**Goal:** Переместить все файлы из `docs/claude/qex/` в `.claude/mcp/qex/`, обновив внутренние ссылки.

**Контекст:** Документация qex сейчас в `docs/claude/qex/` (5 файлов). Переносим в `.claude/mcp/qex/` для портативности. Файлы сами по себе не содержат ссылок на `docs/claude/qex` (только относительные `./SETUP_GUIDE.md` и `./templates/`), поэтому внутренние ссылки сохранятся автоматически. Единственное — блок «Структура папки» в README.md ссылается на `docs/claude/qex/`, его нужно обновить.

**Файлы:**
- `docs/claude/qex/README.md` → скопировать в `.claude/mcp/qex/README.md` (обновить)
- `docs/claude/qex/SETUP_GUIDE.md` → скопировать в `.claude/mcp/qex/SETUP_GUIDE.md` (без изменений)
- `docs/claude/qex/templates/ignore.template` → `.claude/mcp/qex/templates/ignore.template`
- `docs/claude/qex/templates/mcp-config.json.snippet` → `.claude/mcp/qex/templates/mcp-config.json.snippet`
- `docs/claude/qex/templates/post-commit.hook.sh` → `.claude/mcp/qex/templates/post-commit.hook.sh`

**Шаги:**
1. Создать директорию `.claude/mcp/qex/templates/`
2. Скопировать все 5 файлов в новые пути
3. В `.claude/mcp/qex/README.md` обновить блок «Структура папки» (строки 94-101):
   - Заменить `docs/claude/qex/` на `.claude/mcp/qex/`
4. В `.claude/mcp/qex/README.md` обновить строку 29: `cp docs/claude/qex/templates/ignore.template .ignore` → `cp .claude/mcp/qex/templates/ignore.template .ignore`
5. В `.claude/mcp/qex/templates/post-commit.hook.sh` обновить строку 12: `cp docs/claude/qex/templates/post-commit.hook.sh .git/hooks/post-commit` → `cp .claude/mcp/qex/templates/post-commit.hook.sh .git/hooks/post-commit`

**Acceptance criteria:**
- [ ] Все 5 файлов существуют в `.claude/mcp/qex/`
- [ ] Внутренние ссылки (`./SETUP_GUIDE.md`, `./templates/`) работают
- [ ] Блок «Структура папки» в README.md указывает на `.claude/mcp/qex/`
- [ ] Команда `cp` в README.md строка 29 указывает на новый путь
- [ ] Путь в `post-commit.hook.sh` строка 12 указывает на новый путь

**Out of scope:** Удаление старых файлов (Task 3.1). Обновление CLAUDE.md (Task 2.1).

---

### Task 1.2 — Перенос sentrux-документации в `.claude/mcp/sentrux/`

**Level:** Junior (Haiku)
**Assignee:** developer
**Goal:** Переместить `docs/claude/sentrux/README.md` в `.claude/mcp/sentrux/README.md`, обновив внутренние ссылки.

**Контекст:** Единственный файл. Содержит ссылку `../../../CLAUDE.md` (строка 279), которая после переноса будет указывать на `.claude/mcp/sentrux/` → `../../../CLAUDE.md` — глубина та же (3 уровня от корня), ссылка остаётся валидной.

**Файлы:**
- `docs/claude/sentrux/README.md` → скопировать в `.claude/mcp/sentrux/README.md`

**Шаги:**
1. Создать директорию `.claude/mcp/sentrux/`
2. Скопировать `docs/claude/sentrux/README.md` в `.claude/mcp/sentrux/README.md`
3. Проверить ссылку на строке 279: `../../../CLAUDE.md` — из `.claude/mcp/sentrux/` это `.claude` → `mcp` → `sentrux` → 3 уровня вверх = корень. Ссылка корректна, менять не нужно.
4. Обновить строку 69: `python .claude/mcp/bootstrap.py` — путь уже корректный, не менять.

**Acceptance criteria:**
- [ ] Файл `.claude/mcp/sentrux/README.md` существует
- [ ] Ссылка `../../../CLAUDE.md` на строке 279 валидна (3 уровня вверх = корень)

**Out of scope:** Удаление `docs/claude/sentrux/` (Task 3.1). Создание `rules.template.toml` (Task 1.3).

---

### Task 1.3 — Создание `rules.template.toml`

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Создать универсальный шаблон `.claude/mcp/sentrux/rules.template.toml` на основе текущего `.sentrux/rules.toml`, пригодный для нового проекта.

**Контекст:** Текущий `.sentrux/rules.toml` содержит проектоспецифичные слои (framework, services, plugins, application) и границы (boundaries). Шаблон должен содержать структуру с плейсхолдерами и комментариями-инструкциями, чтобы пользователь мог адаптировать под свой проект. bootstrap.py в Phase 2 (Task 2.3) будет копировать этот шаблон в `.sentrux/rules.toml` нового проекта.

**Файлы:**
- `.sentrux/rules.toml` — источник (прочитать для понимания структуры, **НЕ менять**)
- `.claude/mcp/sentrux/rules.template.toml` — создать

**Шаги:**
1. Прочитать текущий `.sentrux/rules.toml` для понимания формата
2. Создать `.claude/mcp/sentrux/rules.template.toml` со следующим содержимым:
   - Заголовочный комментарий: назначение файла, команда копирования (`cp .claude/mcp/sentrux/rules.template.toml .sentrux/rules.toml`), ссылка на sentrux README
   - Секция `[constraints]` с разумными дефолтами:
     - `min_quality = 0.50` (мягкий порог для старта)
     - `max_cycles = 0`
     - `no_god_files = true`
   - Секция `[[layers]]` с 2-3 примерами-плейсхолдерами (закомментированными):
     ```toml
     # [[layers]]
     # name  = "core"
     # paths = ["src/core/*"]
     # order = 0
     #
     # [[layers]]
     # name  = "app"
     # paths = ["src/app/*"]
     # order = 1
     ```
   - Секция `[[boundaries]]` с 1-2 примерами-плейсхолдерами (закомментированными):
     ```toml
     # [[boundaries]]
     # from   = "src/core/*"
     # to     = "src/app/*"
     # reason = "core не должен зависеть от app"
     ```
   - Комментарии на русском, объясняющие каждую секцию

**Acceptance criteria:**
- [ ] Файл `.claude/mcp/sentrux/rules.template.toml` существует
- [ ] Содержит секции `[constraints]`, `[[layers]]`, `[[boundaries]]` с комментариями
- [ ] Примеры слоёв и границ закомментированы (шаблон не сломает sentrux при копировании as-is)
- [ ] Комментарии на русском объясняют как адаптировать

**Out of scope:** Изменение текущего `.sentrux/rules.toml`. Автоматическое копирование при bootstrap (Task 2.3).

---

### Task 1.4 — Создание `PORTABLE.md`

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Создать `.claude/mcp/PORTABLE.md` — пошаговую инструкцию переноса MCP-инфраструктуры в новый проект.

**Контекст:** Сейчас инструкции по переносу разбросаны между `.claude/mcp/README.md`, `.claude/CLAUDE-SETUP.md`, `docs/claude/qex/README.md`. Нужен единый документ-чеклист, который покрывает полный сценарий «скопировать в новый проект и настроить».

**Файлы:**
- `.claude/mcp/PORTABLE.md` — создать

**Шаги:**
1. Создать `.claude/mcp/PORTABLE.md` со следующей структурой:
   - **Что копировать:** `.claude/mcp/` целиком (идёт вместе с `.claude/`)
   - **Что НЕ копировать:** `.mcp.json` (генерируется bootstrap), `.sentrux/rules.toml` (адаптировать из шаблона), `.sentrux/baseline.json` (генерируется sentrux)
   - **Чеклист переноса (пронумерованные шаги):**
     1. Скопировать `.claude/` в новый проект
     2. `python .claude/mcp/bootstrap.py` — проверит зависимости, создаст `.mcp.json`
     3. Адаптировать `.ignore` из `.claude/mcp/qex/templates/ignore.template`
     4. Адаптировать `.sentrux/rules.toml` из `.claude/mcp/sentrux/rules.template.toml`
     5. Запустить `ollama serve`
     6. Перезапустить Claude Code
     7. Проиндексировать: `mcp__qex__index_codebase(path=..., force=true)`
     8. Проверить: `/mcp` — qex и sentrux зелёные
   - **Опциональные шаги:**
     - Установка git hooks (`pre-push` из `scripts/hooks/pre-push`, `post-commit` из `.claude/mcp/qex/templates/post-commit.hook.sh`)
     - Настройка Context7 (`npx -y ctx7 setup --claude`)
   - **Ссылки на детальные гайды:**
     - qex: `.claude/mcp/qex/README.md` (quick-start), `.claude/mcp/qex/SETUP_GUIDE.md` (полный)
     - sentrux: `.claude/mcp/sentrux/README.md`
     - bootstrap: `.claude/mcp/README.md`
   - Язык — русский

**Acceptance criteria:**
- [ ] Файл `.claude/mcp/PORTABLE.md` существует
- [ ] Содержит пронумерованный чеклист переноса (минимум 8 шагов)
- [ ] Явно указано что копировать и что НЕ копировать
- [ ] Все ссылки на гайды указывают на новые пути (`.claude/mcp/...`)
- [ ] Язык — русский

**Out of scope:** Автоматизация переноса (bootstrap уже это делает частично).

---

### Task 2.1 — Обновление ссылок в `CLAUDE.md`

**Level:** Junior (Haiku)
**Assignee:** developer
**Goal:** Обновить 3 ссылки в корневом `CLAUDE.md`, указывающие на старые пути документации.

**Контекст:** После переноса документации в Phase 1, ссылки в CLAUDE.md должны указывать на новые пути. CLAUDE.md — главный контекстный файл проекта, читается агентами при каждом запуске.

**Файлы:**
- `CLAUDE.md` — обновить 3 ссылки

**Шаги:**
1. Строка 34: заменить `docs/claude/qex/README.md` на `.claude/mcp/qex/README.md`
2. Строка 34: заменить `docs/claude/qex/SETUP_GUIDE.md` на `.claude/mcp/qex/SETUP_GUIDE.md`
3. Строка 35: заменить `docs/claude/sentrux/README.md` на `.claude/mcp/sentrux/README.md` (текст и ссылка)
4. Строка 150: заменить `docs/claude/sentrux/README.md` на `.claude/mcp/sentrux/README.md` (текст и ссылка)

**Полные замены (для точности):**

Строка 34 (ключевые пути):
```
БЫЛО: | Настройка qex | `docs/claude/qex/README.md` (quick-start), `docs/claude/qex/SETUP_GUIDE.md` (полный) |
СТАЛО: | Настройка qex | `.claude/mcp/qex/README.md` (quick-start), `.claude/mcp/qex/SETUP_GUIDE.md` (полный) |
```

Строка 35:
```
БЫЛО: | Гайд по sentrux | [`docs/claude/sentrux/README.md`](docs/claude/sentrux/README.md) (метрики, slash-команды, сценарии) |
СТАЛО: | Гайд по sentrux | [`.claude/mcp/sentrux/README.md`](.claude/mcp/sentrux/README.md) (метрики, slash-команды, сценарии) |
```

Строка 150:
```
БЫЛО: Гайд по sentrux: [`docs/claude/sentrux/README.md`](docs/claude/sentrux/README.md).
СТАЛО: Гайд по sentrux: [`.claude/mcp/sentrux/README.md`](.claude/mcp/sentrux/README.md).
```

**Acceptance criteria:**
- [ ] В CLAUDE.md нет ни одного упоминания `docs/claude/qex/` или `docs/claude/sentrux/`
- [ ] Все 3 ссылки указывают на `.claude/mcp/qex/` и `.claude/mcp/sentrux/` соответственно
- [ ] `grep -c "docs/claude/qex\|docs/claude/sentrux" CLAUDE.md` возвращает 0

**Out of scope:** Другие правки в CLAUDE.md. Обновление `.claude/` CLAUDE.md (там нет этих ссылок).
**Dependencies:** Task 1.1, Task 1.2

---

### Task 2.2 — Обновление `.claude/mcp/README.md` как master guide

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Обновить `.claude/mcp/README.md`, добавив ссылки на подпапки `qex/`, `sentrux/`, новые файлы `PORTABLE.md` и `rules.template.toml`.

**Контекст:** Текущий README уже содержит описание MCP-серверов, bootstrap, troubleshooting. Нужно расширить таблицу «Состав», добавить раздел-ссылку на подпапки и PORTABLE.md.

**Файлы:**
- `.claude/mcp/README.md` — обновить

**Шаги:**
1. Обновить таблицу «Состав» (строки 8-13) — добавить строки:
   - `qex/` — документация qex (README, SETUP_GUIDE, templates)
   - `sentrux/` — документация sentrux (README, rules.template.toml)
   - `PORTABLE.md` — инструкция переноса в новый проект
2. Добавить новый раздел «Документация MCP-серверов» после «MCP-серверы» (строка 23) со ссылками:
   - `qex/README.md` — quick-start qex
   - `qex/SETUP_GUIDE.md` — полный гайд (Windows + macOS, диагностика)
   - `sentrux/README.md` — метрики, slash-команды, сценарии
   - `sentrux/rules.template.toml` — шаблон архитектурных правил
   - `PORTABLE.md` — чеклист переноса в новый проект
3. НЕ менять секции «Установка», «Troubleshooting», «Платформенная разница» — они актуальны

**Acceptance criteria:**
- [ ] Таблица «Состав» содержит все 7 элементов (4 старых + 3 новых)
- [ ] Раздел «Документация MCP-серверов» содержит ссылки на все подпапки
- [ ] Ссылка на PORTABLE.md присутствует

**Out of scope:** Переписывание существующих секций README.
**Dependencies:** Task 1.1, 1.2, 1.3, 1.4

---

### Task 2.3 — Обновление `bootstrap.py` (копирование `rules.template.toml`)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Добавить в `bootstrap.py` шаг 5: копирование `.claude/mcp/sentrux/rules.template.toml` → `.sentrux/rules.toml` (с защитой от перезаписи).

**Контекст:** Сейчас bootstrap проверяет sentrux, ollama, Context7 и копирует `.mcp.json`. Не хватает инициализации `.sentrux/rules.toml` для нового проекта. Шаблон rules создан в Task 1.3.

**Файлы:**
- `.claude/mcp/bootstrap.py` — обновить

**Шаги:**
1. Добавить константу `RULES_TEMPLATE = SCRIPT_DIR / "sentrux" / "rules.template.toml"`
2. Добавить константу `RULES_TARGET = PROJECT_ROOT / ".sentrux" / "rules.toml"`
3. Изменить `step(1, 4, ...)` на `step(1, 5, ...)` и далее (total = 5 вместо 4)
4. Добавить шаг 5 после шага 4 (перед «Итог»):
   ```python
   step(5, 5, ".sentrux/rules.toml (архитектурные правила)...")
   ```
   - Если `RULES_TEMPLATE` не существует — `err("Template не найден: ...")`, но НЕ `sys.exit(1)` (не критично)
   - Если `.sentrux/` не существует — создать директорию
   - Если `RULES_TARGET` уже существует — `ok(".sentrux/rules.toml уже существует (пропускаю)")`, НЕ перезаписывать
   - Если не существует — скопировать, `ok(".sentrux/rules.toml создан из template")`
5. Обновить финальный блок «Дальше:» — добавить пункт: `"  4. Отредактируй .sentrux/rules.toml под свой проект (слои и границы)"`
6. Обновить docstring (строка 14): изменить «Что делает:» — добавить пункт 5

**Acceptance criteria:**
- [ ] bootstrap.py содержит 5 шагов (было 4)
- [ ] При запуске на новом проекте создаётся `.sentrux/rules.toml` из шаблона
- [ ] При запуске на существующем проекте `.sentrux/rules.toml` не перезаписывается
- [ ] Если шаблон отсутствует — warning, но скрипт не падает

**Out of scope:** Изменение логики шагов 1-4. Копирование `.ignore` (это отдельный ручной шаг по PORTABLE.md).
**Dependencies:** Task 1.3

---

### Task 3.1 — Удаление старых директорий

**Level:** Junior (Haiku)
**Assignee:** developer
**Goal:** Удалить `docs/claude/qex/` и `docs/claude/sentrux/` после переноса.

**Контекст:** После Phase 1-2 все файлы перенесены и все ссылки обновлены. Старые директории можно безопасно удалить. Проверить перед удалением, что в проекте не осталось ссылок.

**Файлы:**
- `docs/claude/qex/` — удалить целиком (5 файлов)
- `docs/claude/sentrux/` — удалить целиком (1 файл)

**Шаги:**
1. Выполнить grep по всему проекту: `grep -r "docs/claude/qex\|docs/claude/sentrux" .` — должно быть 0 результатов
2. Если grep чистый — удалить `docs/claude/qex/` рекурсивно
3. Удалить `docs/claude/sentrux/` рекурсивно
4. Проверить, не осталась ли `docs/claude/` пустой. Если в ней есть другие файлы (`memory/` и пр.) — оставить. Если пустая — удалить.

**Acceptance criteria:**
- [ ] Директория `docs/claude/qex/` не существует
- [ ] Директория `docs/claude/sentrux/` не существует
- [ ] `grep -r "docs/claude/qex\|docs/claude/sentrux" .` возвращает 0 результатов
- [ ] `docs/claude/` содержит только оставшиеся файлы (memory и т.д.) или удалена если пуста

**Out of scope:** Удаление `docs/claude/memory/` или других файлов в `docs/claude/`.
**Dependencies:** Task 2.1, Task 2.2

**Edge cases:**
- Если `docs/claude/` содержит только `memory/` — оставить директорию
- Проверить `.gitignore` — убедиться что `docs/claude/qex/` не упомянут в gitignore (нет специальных правил)

---

## Риски и ограничения

1. **Скрытые файлы в `.claude/`:** ripgrep/qex по умолчанию игнорируют hidden-директории. Перенос документации в `.claude/mcp/` означает, что qex не будет индексировать эти файлы. Но это документация, а не код — для поиска по ней используется Read, не qex. Риск минимален.

2. **Размер `.claude/` при копировании:** добавляется ~6 файлов документации (~30 KB). Незначительно.

3. **Обратная совместимость ссылок:** после удаления старых путей, если кто-то работает на старой ветке — ссылки сломаются. Но это обычный рефакторинг, решается мержем.

## Оценка объёма

| Задача | Файлов (новых/изменённых) | Строк правок |
|--------|--------------------------|--------------|
| Task 1.1 | 5 новых | ~10 строк правок в README |
| Task 1.2 | 1 новый | 0 правок |
| Task 1.3 | 1 новый | ~40 строк |
| Task 1.4 | 1 новый | ~80 строк |
| Task 2.1 | 1 изменённый | 4 строки |
| Task 2.2 | 1 изменённый | ~20 строк |
| Task 2.3 | 1 изменённый | ~30 строк |
| Task 3.1 | 6 удалённых | 0 строк |
| **Итого** | 8 новых, 3 изменённых, 6 удалённых | ~184 строки |
