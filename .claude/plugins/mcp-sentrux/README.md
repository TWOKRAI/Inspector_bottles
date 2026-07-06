# sentrux — архитектурный health-gate

**sentrux** ([github.com/sentrux/sentrux](https://github.com/sentrux/sentrux)) — структурный анализатор кодовой базы. Один Rust-бинарь, без рантайм-зависимостей. Считает граф импортов, метрики связности, циклы — и сводит всё в один **quality_signal** (0–10000), который удобно использовать как gate перед коммитом или мерджем.

В этом проекте sentrux подключён как **MCP-сервер** (Claude Code умеет его звать) + 8 проектных slash-команд `/mcp-sentrux:sentrux-*`.

---

## Что он даёт

| Боль | Как помогает sentrux |
|------|----------------------|
| «У нас всё запутано, но непонятно где именно» | Считает 5 метрик (modularity, acyclicity, depth, equality, redundancy), показывает **bottleneck** — главную причину просадки |
| «Где циклы между модулями?» | `dsm` строит Dependency Structure Matrix и подсвечивает циклы |
| «Рефакторинг не сделал хуже?» | `session_start` фиксирует baseline → правки → `session_end` показывает дельту качества |
| «Какие модули без тестов?» | `test_gaps` находит непокрытые узлы графа — приоритезируя те, у кого много зависимостей |
| «`domain/*` не должен импортировать `adapters/*` — как заставить CI это ловить?» | `.sentrux/rules.toml` + `sentrux check` (exit 0/1, CI-friendly) |
| «Куда мы движемся по качеству — вверх или вниз?» | `evolution` показывает тренды по времени |

**sentrux ортогонален qex:**

- **qex** отвечает на «*где* используется X» (семантический поиск).
- **sentrux** отвечает на «*насколько здорова* архитектура».

Они **не дублируют** друг друга. Не используй sentrux для поиска по коду, не используй qex для оценки связности.

---

## Стартовые архетипы правил

`claude-kit-project new` **автоматически** разворачивает `.sentrux/rules.toml` из архетипа
`rules.src-package.toml` с уже подставленным именем твоего пакета — вписывать руками
ничего не нужно, и проект «зелёный» с первого коммита. Активны сразу `max_cycles` и
`no_god_files`; блок `[[boundaries]]` (граница архитектуры) приезжает **закомментированным**
с предзаполненным именем пакета — раскомментируешь, когда появятся слои-папки
(см. «Зелено с дня 1» ниже). В комплекте есть ещё два архетипа на случай другой архитектуры.

| Архетип | Когда выбирать | Цепочка зависимостей (сверху вниз) |
|---------|----------------|-------------------------------------|
| **`rules.src-package.toml`** | Дефолт seed-скелета (**разворачивается сам**): один `src/<pkg>/`, разбитый на подпакеты | `cli → services → core → utils` |
| **`rules.layered.toml`** | Классический n-tier: каждый слой зависит только от нижнего, инфраструктура в основании | `presentation → application → domain → infrastructure` |
| **`rules.hexagonal.toml`** | Ports & adapters / clean / onion: домен в центре, зависимости направлены внутрь | `app → adapters → ports → domain` |

(`→` = «разрешено импортировать». Восходящие/наружные импорты запрещены.)

Переключиться на другой архетип (выбери одну строку — `src-package` уже развёрнут
по умолчанию):

```bash
cp .claude/plugins/mcp-sentrux/templates/rules.layered.toml   .sentrux/rules.toml
cp .claude/plugins/mcp-sentrux/templates/rules.hexagonal.toml .sentrux/rules.toml
```

> **⚠️ При ручном копировании — обязательная правка, иначе правила молча не работают.**
> (Авто-деплой `claude-kit-project new` подставляет имя пакета сам; ручные шаги нужны только
> если копируешь архетип руками.) sentrux матчит пути в `[[boundaries]]` как
> **литеральные префиксы директорий** — `*` подставляет только имя файла и **не**
> раскрывает сегменты-директории. Поэтому `src/*/core` не матчит ничего, а boundary,
> который ничего не матчит, **проходит молча** (ложное ощущение защиты). После копирования:
> 1. замени `your_package` на имя своего пакета под `src/` (напр. `src/acme/core`);
> 2. **сними `# ` с блока `[[boundaries]]`** — он, как и в авто-деплое, приезжает
>    закомментированным (пока слоёв-папок нет — `активный` boundary молча проходит);
> 3. проверь, что правила «кусаются» — добавь намеренный восходящий импорт, убедись,
>    что `sentrux check` падает на нём, затем убери его.
>
> Для нескольких пакетов под `src/` продублируй блок `[[boundaries]]` на каждый
> пакет (пути литеральные). Полностью закомментированный «голый» каркас со всеми
> типами правил — в [`rules.template.toml`](rules.template.toml).

### Зелено с дня 1

Архетипы **активны, но не мешают** на старте:

- Активны `max_cycles = 0` и `no_god_files = true` — оба зелёные на чистом коде и
  ловят реальные проблемы сразу.
- Метрики-минимумы (`min_modularity`, `min_redundancy` и пр.) **закомментированы**:
  новый/маленький проект законно не дотягивает до них даже без реальных нарушений.
  Раскомментируй и подними их, когда кодовая база созреет.
- Блок `[[boundaries]]` (направление зависимостей между слоями) тоже приходит
  **закомментированным** — намеренно. На свежем проекте слоёв-папок ещё нет, а
  *активный* boundary, который ничего не матчит, **проходит молча** и создаёт ложное
  ощущение, что архитектура под защитой. Имя пакета в нём уже подставлено: когда
  появятся `src/<pkg>/core` и т.д., просто сними `# ` с блока (и проверь, что
  «кусается» — добавь намеренный плохой импорт, убедись что `sentrux check` падает).

Так нет ни ложного «красного» в день 1, ни ложного «зелёного»: всё, что активно —
реально работает, а всё, что ещё не применимо — видимо закомментировано.

> **⚠️ Слепые зоны sentrux 0.5.7 (boundary молча пропускает).** Когда раскомментируешь
> `[[boundaries]]`, учти два места, где они **не** срабатывают:
> - **Relative-импорты не резолвятся:** `from ..cli import x` обходит границу молча.
>   В гейтируемых слоях используй **абсолютные** импорты (`from <pkg>.cli import x`)
>   — или добавь lint-правило, запрещающее relative-импорты.
> - **Плоский модуль** `src/<pkg>/<layer>.py` **не** матчится dir-путём
>   `src/<pkg>/<layer>` — держи слои подпакетами (`src/<pkg>/<layer>/`) либо добавь
>   суффикс `.py` в путь boundary для плоского слоя.

---

## Установка

> Быстрый путь «установить → подключить → проверить» — [`SETUP_GUIDE.md`](SETUP_GUIDE.md).
> Ниже — подробности по платформам.

### macOS

```bash
brew install sentrux/tap/sentrux
```

Grammars скачаются при первом запуске автоматически.

### Linux

```bash
curl -fsSL https://raw.githubusercontent.com/sentrux/sentrux/main/install.sh | sh
```

### Windows

**Вариант 1 — curl (рекомендуется, если есть Rust toolchain):**

```powershell
# Скачать бинарь в ~/.cargo/bin/ (уже в PATH если Rust установлен)
curl -L -o "%USERPROFILE%\.cargo\bin\sentrux.exe" ^
  https://github.com/sentrux/sentrux/releases/latest/download/sentrux-windows-x86_64.exe

# Проверить
sentrux --version
```

Grammars (51 языковой парсер) скачаются при первом запуске автоматически (~30 MB).

**Вариант 2 — ручная установка:**

1. Скачать `sentrux-windows-x86_64.exe` из [latest release](https://github.com/sentrux/sentrux/releases/latest)
2. Переименовать в `sentrux.exe`
3. Положить в любую директорию из PATH (например `%USERPROFILE%\.cargo\bin\` или `%USERPROFILE%\bin\`)

**Вариант 3 — через claude-kit:**

```bash
claude-kit-project new        # создаёт проект и генерирует .mcp.json из plugin.json включённых плагинов
# или, для существующего проекта:
claude-kit-claude plugin enable mcp-sentrux
```

`claude-kit` автоматически включит sentrux в `.mcp.json` при выборе соответствующего компонента.

### Проверка установки

```bash
sentrux --version          # должно показать "sentrux X.Y.Z"
sentrux check              # должно показать "Quality: NNNN" и список правил
```

### MCP-подключение

MCP-биндинг прописан в `.mcp.json` (бинарь запускается через `sentrux mcp`). После установки перезапусти Claude Code и проверь: `/mcp` → sentrux должен быть зелёным.

---

## Метрики и quality_signal

`quality_signal` — **геометрическое среднее** пяти под-метрик, каждая нормирована в 0–10000.

| Метрика | Что меряет | Низкий score = |
|---------|-----------|----------------|
| **modularity** | Насколько модули внутренне связаны и слабо связаны между собой | Размытые границы, утечка деталей |
| **acyclicity** | Отсутствие циклов в графе импортов | Есть циклы → score падает в пол |
| **depth** | Глубина архитектурных слоёв | Всё в одной плоскости / слишком вложено |
| **equality** | Равномерность распределения сложности по модулям | God-module / десятки крошечных |
| **redundancy** | Дубликаты / повторяющийся код | Много копи-пасты |

Шкала `quality_signal`:

| Диапазон | Интерпретация |
|----------|---------------|
| 0–3000 | Архитектура запутана, рефакторинг неизбежен |
| 3000–6000 | Средне. Видны bottleneck'и, точечные улучшения дадут эффект |
| 6000–8000 | Хорошо. Поддерживаемо, регулярная гигиена |
| 8000–10000 | Отлично. Сохранять текущий уровень |

**Главное правило:** не смотри на абсолютное число — смотри на **дельту** до/после изменений и на **bottleneck**.

---

## Slash-команды (`.claude/commands/sentrux-*`)

### Снимки и анализ

| Команда | Что делает | Когда звать |
|---------|------------|-------------|
| `/mcp-sentrux:sentrux-health` | scan + health, общий снимок: quality_signal + bottleneck + 5 метрик | В начале сессии, чтобы понять «откуда стартуем» |
| `/mcp-sentrux:sentrux-dsm` | Dependency Structure Matrix: связи между модулями, циклы | Когда bottleneck = `acyclicity` или нужно понять «кто кого тянет» |
| `/mcp-sentrux:sentrux-gaps` | Список модулей без тестов (с приоритетом по связности) | Перед `/dev:ship`, перед PR |
| `/mcp-sentrux:sentrux-evolution` | Тренды метрик во времени | Ретроспектива после крупного рефакторинга |

### Workflow рефакторинга

| Команда | Что делает | Когда звать |
|---------|------------|-------------|
| `/mcp-sentrux:sentrux-baseline` | Фиксирует quality_signal как точку отсчёта (`session_start`) | **Перед** началом крупного рефакторинга |
| `/mcp-sentrux:sentrux-diff` | Сравнивает текущее состояние с baseline (`session_end`), показывает дельту | **После** правок, перед коммитом |

### Правила и CI

| Команда | Что делает | Когда звать |
|---------|------------|-------------|
| `/mcp-sentrux:sentrux-rules` | Проверка `.sentrux/rules.toml` через MCP, интерактивный разбор нарушений | После изменения границ слоёв / новых импортов |
| `/mcp-sentrux:sentrux-check` | CLI `sentrux check` (exit 0/1, для pre-commit и CI) | В скриптах, в pre-commit, в CI |

---

## Типичные сценарии

### 1. Перед рефакторингом

```
/mcp-sentrux:sentrux-baseline       # фиксируем точку отсчёта
... делаешь правки ...
/mcp-sentrux:sentrux-diff           # видишь signal_before → signal_after
```

Если `signal_after < signal_before` — что-то поломал. Запусти `/mcp-sentrux:sentrux-dsm` чтобы найти, где появились новые связи или циклы.

### 2. Поиск циклов

```
/mcp-sentrux:sentrux-health         # bottleneck = acyclicity, score 2500/10000
/mcp-sentrux:sentrux-dsm            # видим какие модули замкнулись
```

Кандидаты на разрыв цикла:

- вынести общий код в нижний слой;
- инвертировать зависимость через интерфейс / событие;
- разбить «толстый» модуль на два.

### 3. Перед `/dev:ship` (PR)

```
/mcp-sentrux:sentrux-gaps           # что не покрыто тестами — закрываем критичное
/mcp-sentrux:sentrux-check          # правила архитектуры не нарушены
/mcp-sentrux:sentrux-diff           # качество не упало относительно baseline
```

### 4. Настройка инвариантов

Обычно `.sentrux/rules.toml` уже развёрнут `claude-kit-project new` (архетип `src-package`).
Если правишь руками — минимальный пример (DIP / hexagonal-стиль):

```toml
[constraints]
max_cycles   = 0
no_god_files = true

# Пути в [[boundaries]] — ЛИТЕРАЛЬНЫЕ префиксы директорий: `*` подставляет имя файла
# и НЕ раскрывает сегмент-директорию, поэтому "src/*/domain" не матчит ничего.
# Используй полный путь src/<pkg>/<layer> (без хвостового слэша). Ключи: from/to/reason
# (ключа `forbidden` НЕТ — sentrux молча игнорирует неизвестные ключи).
[[boundaries]]
from   = "src/your_package/domain"
to     = "src/your_package/adapters"
reason = "domain не зависит от adapters (DIP)"
```

> Это generic-пример. Подгони пути под реальные слои/пакет своего проекта, либо
> возьми готовый архетип из `templates/` (см. «Стартовые архетипы правил» выше).

Дальше:

```
/mcp-sentrux:sentrux-rules          # проверка через MCP — интерактивно
/mcp-sentrux:sentrux-check          # та же проверка через CLI — для CI
```

---

## MCP-инструменты (девять)

Slash-команды выше — обёртки над этими MCP-tool'ами. Их можно звать и напрямую (если нужна нестандартная комбинация):

| Tool | Назначение |
|------|-----------|
| `mcp__sentrux__scan` | Полный пересчёт метрик (обязателен перед остальными в новой сессии) |
| `mcp__sentrux__rescan` | Быстрое обновление после правок |
| `mcp__sentrux__health` | quality_signal + bottleneck + 5 метрик |
| `mcp__sentrux__dsm` | Dependency Structure Matrix |
| `mcp__sentrux__test_gaps` | Модули без тестов |
| `mcp__sentrux__check_rules` | Валидация `.sentrux/rules.toml` |
| `mcp__sentrux__session_start` | Сохранить baseline |
| `mcp__sentrux__session_end` | Сравнить с baseline (pass/fail + дельта) |
| `mcp__sentrux__evolution` | Историческая динамика |

---

## CLI (без MCP)

Полезно для CI / pre-commit / скриптов. Работает одинаково на macOS, Linux, Windows:

```bash
sentrux                        # GUI с live-treemap (если есть дисплей)
sentrux check                  # валидация rules.toml, exit 0/1
sentrux gate --save            # сохранить baseline
sentrux gate                   # сравнить с baseline (CI-режим)
sentrux mcp                    # запустить MCP-сервер (это и делает .mcp.json)
sentrux plugin list            # языковые плагины
```

> **Примечание:** в v0.5.7+ путь к проекту определяется автоматически (текущая директория). Аргумент `.` не нужен.

---

## Диагностика

**`/mcp` показывает sentrux как failed**

```bash
# macOS / Linux
which sentrux                  # бинарь должен быть в PATH
sentrux mcp --help             # должно быть "Start the MCP server"

# Windows (Git Bash)
where sentrux                  # или: which sentrux
sentrux mcp --help
```

Если бинарь есть, но MCP всё равно падает — перезапусти Claude Code:
- VS Code: `Ctrl+Shift+P` (Windows) / `Cmd+Shift+P` (macOS) → `Developer: Reload Window`
- CLI: перезапустить терминал

**`scan` слишком долгий**

Большой проект → проверь `.gitignore` и `.ignore`. sentrux уважает их (как ripgrep). Уберите из индексации архивы, бинарники, генерёнку.

**`session_end` говорит "no baseline"**

Сначала `/mcp-sentrux:sentrux-baseline`, потом правки, потом `/mcp-sentrux:sentrux-diff`. Baseline хранится в памяти MCP-сервера — пережить рестарт Claude Code не сможет.

**Метрики не меняются после правок**

`mcp__sentrux__rescan` или просто `/mcp-sentrux:sentrux-health` (он зовёт scan заново).

---

## Источники

- Репозиторий: <https://github.com/sentrux/sentrux>
- Установка/релизы: <https://github.com/sentrux/sentrux/releases>
- Pro-версия (продвинутые root-cause диагностики): <https://github.com/sentrux/sentrux> → Upgrade

Полный список slash-команд проекта — в корневом [`CLAUDE.md`](../../../CLAUDE.md), раздел «Проектные команды».
## Launcher options

**Default** (used automatically by `claude-kit-claude plugin enable mcp-sentrux`): declared inline in `.claude-plugin/plugin.json` → `mcpServers.sentrux`.

```
command: sentrux
args: ["mcp"]
```

Requires the `sentrux` binary in PATH (see "Setup" above).

Switching: edit `.mcp.json` manually (it's not regenerated for non-manifest content).
