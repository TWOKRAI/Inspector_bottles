# Atlas — базовые метрики до изменений (Task 0.6)

- **Дата замера:** 2026-10-04. Дерево: worktree `atlas`, HEAD `ce3920df2`; `main` = `6421c2560`.
- **Окно «60 дней»:** 2026-08-05 … 2026-10-04.
- **Замерщик:** read-only. В репозиторий ничего не записано. Скрипты — `research/baseline_scripts/` (`m1.py` … `m8.py`), команды ниже воспроизводимы.
- Python: `PYTHONUTF8=1 D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe`.
- qex не использовался (индекс устарел, Ollama выключен). Всё — `git grep`, `git log`, `git show`, разбор транскриптов.

## Сводка (8 чисел)

| # | Метрика | База | Уверенность |
|---|---------|------|-------------|
| 1 | Имена из `interfaces.py::__all__` с упоминанием в `tests/` своего модуля | **50 из 118 = 42,4 %**; гарантии с инъекцией и мутационный балл — `n/a` | средняя (см. оговорку) |
| 2 | `SURFACE_CHANGED_WITHOUT_TEST` на 60 днях | **1 из 33** (3,0 %) по заданному определению; строгие варианты 8/39 и 16/55 | высокая для счёта, низкая для смысла |
| 3 | Дефекты живого стенда после ревью | **≈ 15 дефектов/находок за 60 дней** по тексту коммитов; тренд вверх, не вниз | низкая (текстовый майнинг) |
| 4 | Цена входа агента (`developer`/`teamlead`) | **контекст при первой правке: медиана 142 тыс.**, разброс 78–251 тыс.; новые токены: медиана 140 тыс. | средняя (n = 94) |
| 5 | Доля задач с `atlas card`/`pack` | **0 %** по построению (инструмента нет) | — |
| 6 | Мест на один факт (D1–D10) | **1–19**, медиана ≈ 8–10; цель 1 (см. таблицу) | средняя |
| 7 | Размеры | `MEMORY.md` git **7 222 Б** (было 33 392); корневой `CLAUDE.md` **26 889 Б**; `.claude/CLAUDE.md` **30 099 Б** | высокая |
| 8 | Повторные грабли | **30 из 184 = 16,3 %** (33 из 184 = 17,9 % с самоописанными повторами) | низкая (метод слабый) |

---

## 1. Доказанность по модулю (до Atlas)

**Команда:** `python plans/2026-10-04_atlas/research/baseline_scripts/m1.py` (читает `git show HEAD:<путь>`; `ast` разбирает `__all__` в `interfaces.py`; имя ищется как слово в `git ls-files <модуль>/tests` через regex `(?<![A-Za-z0-9_])имя(?![A-Za-z0-9_])`).
**Окно:** срез HEAD `ce3920df2`, один момент. **n:** 27 модулей, 118 публичных имён.

Сырой вывод (`TOTAL 118 50 42.4`):

| модуль | имён в `__all__` | упомянуто в `tests/` | доля |
|---|---|---|---|
| actions_module | 3 | 0 | 0 % |
| app_module | 6 | 4 | 66 % |
| base_manager | 3 | 2 | 66 % |
| chain_module | 7 | 4 | 57 % |
| channel_routing_module | 4 | 1 | 25 % |
| command_module | 1 | 0 | 0 % |
| config_module | 3 | 0 | 0 % |
| console_module | 2 | 1 | 50 % |
| data_schema_module | 17 | 3 | 17 % |
| dispatch_module | 2 | 1 | 50 % |
| display_module | 3 | 1 | 33 % |
| error_module | 6 | 5 | 83 % |
| event_module | 2 | 0 | 0 % |
| frontend_module | 21 | 9 | 42 % |
| logger_module | 5 | 3 | 60 % |
| message_module | 1 | 1 | 100 % |
| process_manager_module | 3 | 3 | 100 % |
| process_module | 4 | 3 | 75 % |
| recipe | 3 | 3 | 100 % |
| registers_module | 1 | 0 | 0 % |
| router_module | 2 | 1 | 50 % |
| service_module | 2 | 2 | 100 % |
| shared_resources_module | 6 | 0 | 0 % |
| state_store_module | 4 | 0 | 0 % |
| statistics_module | 1 | 1 | 100 % |
| telemetry_readmodel_module | 1 | 0 | 0 % |
| worker_module | 5 | 2 | 40 % |
| **Итого** | **118** | **50** | **42,4 %** |

- 8 модулей из 27 имеют 0 %: actions, command, config, event, registers, shared_resources, state_store, telemetry_readmodel.
- **Оговорка о смысле.** В `__all__` большинства модулей лежат Protocol-интерфейсы (`IConfig`, `IStateStore`, `IRouter` …). Тесты используют реализации, а не имя протокола. Пример: `state_store_module` — 691 собранный тест (`pytest --collect-only`, O1), 31 тестовый файл, и 0 из 4 имён протокола в нём названы. Метрика меряет «имя названо», а не «свойство доказано». Она годится как нижняя планка и как база для сравнения, но не как доказательство.
- **Гарантии с инъекцией:** `n/a`. Единого маркера гарантий в коде не проверял и не нашёл; `atlas` его ещё не вводит. Будет измерено после Task 1.x по строке доказанности карточки.
- **Мутационный балл:** `n/a`. Файл `scripts/mutation_gate.py` существует; я его не запускал и не проверял, публикует ли он балл по модулям. Будет измерено после появления гейта в CI (фаза 2), по CI-артефактам.

## 2. SURFACE_CHANGED_WITHOUT_TEST (60 дней, `main`)

**Определение (по заданию).** В first-parent диапазоне `main` за 60 дней: коммит/слияние меняет `interfaces.py` (любой) или `__all__` в `multiprocess_framework/modules/*/__init__.py` и не трогает ни одного файла под `tests/` или `test_*.py`. Для слияния берётся `git diff --name-only <m>^1 <m>`.

**Команды:**
```
git log --first-parent main --since=60.days --format=%H | wc -l          -> 832
python plans/2026-10-04_atlas/research/baseline_scripts/m2.py     # вариант A (определение выше)
python plans/2026-10-04_atlas/research/baseline_scripts/m2b.py    # варианты B и C (строже)
```
**Окно:** 2026-08-05 … 2026-10-04 (первый коммит окна `23184cc48` от 2026-08-09, последний `03952a02`). **n:** 832 first-parent коммита, из них 33 меняют поверхность.

**Результат A: 1 из 33 = 3,0 %.**
SHA без теста: `1e3c60c3b` (2026-08-31, `feat(observability): Task 1.3b — одна дверь «факт + голос»`, меняет `error_module/interfaces.py`, 0 файлов тестов).

Строже (тот же счёт, но тест должен лежать в том же модуле):

| вариант | знаменатель | без теста в том же модуле | доля |
|---|---|---|---|
| A: любой тест в диапазоне (как в плане) | 33 first-parent | 1 | 3,0 % |
| B: тест в каталоге того же модуля, first-parent | 39 first-parent | 8 | 20,5 % |
| C: каждый не-merge коммит отдельно, тест того же модуля | 55 из 1873 не-merge коммитов | 16 | 29,1 % |

SHA варианта B: `a6984d468`, `b7babad60`, `97564e428`, `757a2d4c6`, `1e3c60c3b`, `c2eec8a8d`, `e805ed9b1`, `23184cc48`.
SHA варианта C: `bb085a9ee`, `dfb0a6b3f`, `a6984d468`, `08c01a33b`, `20f7e7e02`, `dd1491e37`, `7c9fbf0cd`, `0e5137871`, `7be18734a`, `97564e428`, `757a2d4c6`, `1e3c60c3b`, `c2eec8a8d`, `e805ed9b1`, `657ceae69`, `68ad1ed78`.

**Вывод для гейта SURFACE.** По определению плана частота **низкая**: 1 за 60 дней. Блокирующий гейт на нём почти не сработает; он поймает редкий случай. Строгий вариант B/C даёт 20–29 %, но часть — интерфейсные правки без нового поведения (docstring, `__all__` без смысла). Решение «блок или нет» принимает K1.1 по повтору того же скрипта.

**Слабости метода:**
- Определение A проверяет тест «в диапазоне слияния», а не «тест на эту поверхность». Слияние длинной ветки почти всегда тянет какой-нибудь тест.
- Разное число в A (33) и B (39) — из-за эвристики для `__init__.py` (смотрит строки `__all__`/элементы списка в диффе). Обе эвристики грубые.
- Правка docstring в `interfaces.py` считается «изменением поверхности».
- Включены `Services/**/interfaces.py` и подмодули (`.../memory/interfaces.py`).

## 3. Дефекты живого стенда после ревью (низкая уверенность)

**Метод:** текстовый майнинг.
1. `git grep` по `docs/reviews`, `docs/sessions`, `plans/**/amendments.md` фразами «живой стенд», «стенд нашёл», «live stand» и вариантами. Результат: узкие фразы дают 2 строки за 60 дней; широкие («стенд») — 13 строк с дефект-словом и почти все не про находку.
2. Основной источник — темы коммитов: `plans/2026-10-04_atlas/research/baseline_scripts/m3.py`: `git log main --no-merges --since=2026-08-05` с темой, где есть (находк|дефект|сломал|врал|вскры|выявил|нашёл) **и** (стенд|живь|живой|живого|живом). 15 попаданий.
3. Плюс ручное чтение: `docs/reviews/2026-10-02_transport-system-review-cto.md:164` («стенд нашёл два факта, которых не предсказал никто») — 1 событие за 2026-10-02.

**Команды:**
```
git grep -nIiE "(живой|живым|живого|живом) стенд[а-я]* (нашёл|показал|выявил)|стенд (нашёл|поймал|выявил)|live stand (found|caught)" -- docs/reviews docs/sessions 'plans/**/amendments.md'
python plans/2026-10-04_atlas/research/baseline_scripts/m3.py
```
**Окно:** 2026-08-05 … 2026-10-04. **n:** 15 коммитов + 1 запись ревью = 16 событий; из них исключено 1 (`7cd082f7c` — находки инъекций, не стенда) → **15**.

Ведро — две недели, конец у 2026-10-04:

| ведро | событий | коммиты |
|---|---|---|
| 08-05 … 08-09 (5 дней, неполное) | 1 | `083b85272` |
| 08-10 … 08-23 | 1 | `fa757046e` |
| 08-24 … 09-06 | 4 | `ea4ea114c`, `4a3614ebb`, `c0fc865da`, `0bc08a6a6` |
| 09-07 … 09-20 | 1 | `97b76beb3` (проба стенда врала — дефект самого зонда, не продукта) |
| 09-21 … 10-04 | 8 | `6e21843d3`, `c2bc060d0`, `26e03e065`, `a34163848`, `1051af40e`, `bd2b52ab2` (R-1..R-3), `704119340`, запись CTO 10-02 (4.7d) |

**Тренд: вверх (1 → 1 → 4 → 1 → 8).** Но это не «качество упало»: в последние две недели стенд гоняли чаще (line-sim, layer-render). Знаменателя «сколько прогонов стенда» нет. Нужна нормировка «дефектов на прогон» — её поставит `atlas log` или поле в `agent-journal`.

**Слабости метода (все существенные):**
- Тема коммита — не доказательство, что дефект найден **после ревью**. Порядок «ревью → стенд» не проверен ни в одном случае.
- Не-ASCII фразы пропускают синонимы («на стенде вылез», «живой прогон вскрыл»).
- Один коммит может содержать несколько дефектов (R-1..R-3 посчитаны как один коммит); другой коммит — ни одного настоящего.
- Число не воспроизводимо между людьми: порог «это дефект стенда» — моё чтение темы.

## 4. Цена входа агента (токены до первой правки)

**Инструмент:** `scripts/agent_report.py` **не существует.** `git log --all -S"agent_report.py" -- scripts` — пусто; в дереве нет файла. Он упомянут в `.claude/plugins/dev/skills/team-protocol/SKILL.md:83`, `.claude/plugins/dev/templates/executor-brief.md:92` и в `plan.md` (Task 0.6) как `--live`. Ссылка висит в пустоту. **Это находка:** ссылки на `agent_report.py --live` в двух документах и в плане указывают на несуществующий скрипт.

**Замена:** `plans/2026-10-04_atlas/research/baseline_scripts/m4.py`. Читает транскрипты субагентов `C:/Users/INNOTECH/.claude/projects/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/<сессия>/subagents/agent-*.jsonl` + `.meta.json` (поле `agentType`). Берёт агентов `developer` и `teamlead`. Первая правка = первое сообщение ассистента с вызовом `Edit`/`Write`/`MultiEdit`/`NotebookEdit`/правок serena. Считает:
- **контекст при первой правке** = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens` в этом сообщении (размер окна);
- **новые токены до первой правки** = сумма `input_tokens + cache_creation_input_tokens + output_tokens` по сообщениям до него включительно (без cache_read; ближе к «total_tokens» инструмента);
- ходы до первой правки.

**Команда:** `python plans/2026-10-04_atlas/research/baseline_scripts/m4.py`.
**Окно:** транскрипты охватывают 2026-09-04 … 2026-10-04 (старше нет). **n:** 94 запуска (≈70 `developer`, ≈25 `teamlead`; ±1 — агенты ещё пишутся).

| показатель | min | p25 | медиана | p75 | max |
|---|---|---|---|---|---|
| контекст при первой правке, токены | 77 921 | 110 156 | **142 044** | 168 088 | 251 297 |
| новые токены до первой правки | 51 821 | 107 028 | **139 556** | 190 246 | 2 030 388 |
| ходы до первой правки | 2 | 6 | **11** | 20 | 117 |

- Медиана `developer` — 135 503, `teamlead` — 146 785 (контекст). С 2026-09-20: медиана 133 773, n = 80.
- Выброс 2,03 млн: `Implement Task 5.5c part A (gate)`, 117 ходов. Медиана и квартили его не замечают.
- Согласие со вторичным источником: `.claude/CLAUDE.md` пишет «107–228 тыс. на вход в задачу»; наша медиана 140 тыс. внутри этого диапазона. Первичный источник — наш замер.
- **Kill №1** (цена входа упала < 20 %): порог = медиана контекста 142 тыс. → 114 тыс. или ниже; по новым токенам 140 тыс. → 112 тыс. или ниже.

**Слабости метода:** первая «правка» может быть записью в scratchpad (не правкой задачи); часть агентов — перезапуск после ревью (вход дешевле); нет разреза «разведка до правки» против «чтение брифа»; контекст включает ~50 тыс. фиксированной базы (CLAUDE.md, память, системный промпт) — её изменит Task 0.4/2.4, это не эффект карточки.

## 5. Доля задач с `atlas card`/`pack`

- **База: 0 %** по построению. Инструмента `atlas` нет (`scripts/atlas/` не существует).
- **Источник замера после появления инструмента:**
  1. `data/team-journal.jsonl` (хук `.claude/plugins/dev/hooks/team-journal.sh`: события `SubagentStart/Stop`, `agent_type`, `agent_id`, `branch`; сегодня 138 строк) — знаменатель «задач»;
  2. транскрипты субагентов (как в п. 4): вызовы `Bash` с `atlas card` / `atlas pack` по `agentId` — числитель;
  3. `data/agent-journal.jsonl` (хук `.claude/plugins/observability/hooks/agent-journal.sh`, 511 строк на 2026-10-04) — второй знаменатель.
- Для K1.1 нужно связать запуск агента с задачей (`Task X.Y`): в журналах поля задачи нет, она только в описании субагента (`meta.json: description`). Это ограничение: до `lint-brief` из 1.6 доля меряется по описанию, не по ключу.

## 6. Мест на один факт (D1–D10)

**Источник списка:** `plans/2026-10-04_atlas/research/O1_sources.md` §2 (D1–D10).
**Команда:** `plans/2026-10-04_atlas/research/baseline_scripts/m6b.sh` (`git grep -lIE <фраза> -- . ':!plans' ':!docs/sessions' ':!docs/handoffs' ':!docs/reviews' ':!docs/claude/memory/_archive' ':!.claude/plugins' ':!.claude/agent-memory' ':!*/tests/*' ':!*DECISIONS.md' …`). Исключены исторические записи, источники плагинов (зеркала материализуются в `.claude/`), тесты, ADR-файлы.
**Окно:** срез HEAD `ce3920df2`. «Место» = файл, который утверждает факт сегодня.

| # | Факт | Фраза поиска | Мест | Какие |
|---|------|--------------|------|-------|
| D1 | Число модулей фреймворка | `(25\|27) модул` | **8 живых** (+1 `OPEN_QUESTIONS`); значения **25 в 4, 27 в 5** — расходятся | `CLAUDE.md` (27 и 25 в одном файле), `MODULES_STATUS.md`, `CONSTRUCTOR_BLUEPRINT.md`, `MODULES_OVERVIEW.md` (25), `MODULES_RESPONSIBILITY_MAP.md` (27 и 25), `MODULE_CONTRACTS.md` (25), `MODULE_TIERS.md`, `docs/README.md` |
| D2 | `Why:`/`Layer:` обязательны | `Layer:?…(обязател\|mandatory\|required)` | **10 говорят «обязателен», 2 — «сейчас необязателен»** | `CLAUDE.md`, `README.md`, `.rules/commits.md`, `.claude/modes/_stack.md`, `.claude/commands/dev/pipeline.md`, `.claude/skills/project-rules/SKILL.md`, `docs/claude/COMMIT_GUIDE.md`, `scripts/README.md`, `scripts/validate_commit/README.md`, `validate_commit.py`; против: `.claude/COMMIT_GUIDE.md:46`, `docs/claude/COMMIT_GUIDE.md:176` |
| D3 | Где живёт память | `dual-write\|autoMemoryDirectory\|Canonical path` | **2 правила + 3 физических дома** | правила: `CLAUDE.md:116`, `.claude/CLAUDE.md:376`; дома: `docs/claude/memory/`, `.claude/memory/` (8 925 Б MEMORY.md), Windows-папка |
| D4 | Где лежат ADR | `docs/claude/DECISIONS/\|docs/decisions/\|modules/X/DECISIONS.md` | **14 файлов, 3 дома** | `modules/X/DECISIONS.md` — 4 (`CLAUDE.md`, `_stack.md`, `.rules/framework.md`, `scripts/sync/adr_modules.py`); `docs/claude/DECISIONS/` — 5 (`/dev:adr`, `sync-context`, `module-contract`, `scripts/aggregate_context` ×2); `docs/decisions/` — 5 (`README`, `reviewer.md`, `direction/README`, `BOOTSTRAP`, `scripts/README`) |
| D5 | Куда класть планы | `workspace/plans\|apps/{app}/plans\|plans/<slug>…` | **19 файлов** (по 4 разным формам пути) | `CLAUDE.md`, `.claude/CLAUDE.md`, `.claude/modes/{_stack,dev}.md`, `.claude/COMMIT_GUIDE.md`, `BOOTSTRAP`, `STACK.md`, 5 команд/агентов, `validate_commit.py`, замороженный `knowledge-plugin` (5) … + глобальный `~/.claude/CLAUDE.md` вне репо |
| D6 | Версии стека (PySide6, torch) | `PySide6 6.1x\|torch>=2.x\|PyTorch 2.x` | **8 файлов**, два значения PySide6 (6.10 и 6.11) | `CLAUDE.md`, `README.md`, `pyproject.toml`, `TECH_STACK_2026.md` (6.10 и 6.11 в одном файле), память `reference_tech_stack_2026.md` (6.11), `project_cuda_torch_setup.md`, `qt_event_bridge.py` |
| D7 | Стартовая точка новой сессии | `handoff-parallel-start` | **1 живое (локальная память Windows) + 0 в git после Task 0.4**; 5 всего-в-git с историей | до 0.4 были две копии `MEMORY.md`; зонд `probe_observability_consumer_acceptance.py:1807` упоминает случайно |
| D8 | Число тестов в `STATUS.md` | `[0-9]+ (тест\|passed\|tests)` в `*STATUS.md` | **29 из 75** `STATUS.md` называют число (каждое — копия факта, который держит pytest) | см. `git grep -lIE '[0-9]+ (тест\|passed\|tests)' -- '*STATUS.md'`; O1 измерил дрейф: 49 против 121, 34 против 46 |
| D9 | Копии индекса памяти | `git ls-files \| grep MEMORY.md` | **3 копии индекса проекта** (`docs/claude/memory/MEMORY.md` 7 222 Б, `.claude/memory/MEMORY.md` 8 925 Б, Windows 7 629 Б) + 8 индексов `agent-memory/*` + 6 в `plugins/core/memory/` (другое содержимое) | |
| D10 | Правило qex-freshness | `get_indexing_status\|Сверка свежести\|qex freshness` | **5 живых** (+ 10 операционных упоминаний в командах, + замороженный `knowledge-plugin`) | `CLAUDE.md:126`, `.claude/CLAUDE.md:172,185`, `.claude/skills/project-rules/SKILL.md`, `docs/claude/memory/MEMORY.md:16`, `feedback_qex_full_rebuild_runbook.md` |

**Итог по таблице:** база = 8–14 мест у D1, D2, D4, D5, D6, D10 (измерение узкое, цель 1); 2–3 места у D3, D7, D9. План писал «сегодня 2–5» — для D2, D4, D5 по узкому счёту это занижено в 2–4 раза. После K1.1 повторять той же командой.

**Слабости метода:**
- Регулярные выражения подбирал я; другая формулировка даст другое число. Счёт — «файл содержит фразу», а не «файл утверждает факт»: D4 и D5 завышены упоминаниями путей в инструкциях, D8 — упоминаниями числа тестов без привязки.
- Зеркала `.claude/plugins/**` исключены (материализуются в `.claude/`), поэтому реальных файлов на диске больше.
- D7: после Task 0.4 индекс в git уже без указателя; база по D7 «до Atlas» = 2 копии (O1), сегодня 1.

## 7. Размеры (байты)

**Команды:**
```
git cat-file -s HEAD:docs/claude/memory/MEMORY.md
git cat-file -s HEAD:CLAUDE.md
git cat-file -s HEAD:.claude/CLAUDE.md
git show main~1:docs/claude/memory/MEMORY.md | wc -c
git show main~1:CLAUDE.md | wc -c ; git show main~1:.claude/CLAUDE.md | wc -c
wc -c C:/Users/INNOTECH/.claude/CLAUDE.md C:/Users/INNOTECH/.claude/projects/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/memory/MEMORY.md
wc -c C:/Users/INNOTECH/.claude/projects/d--PROJECT-INNOTECH-Inspector-vision-Inspector-bottles/memory_backup_2026-10-04/MEMORY.md
```
**Окно:** срез на 2026-10-04 (HEAD `ce3920df2`).

| файл | байт сейчас | байт до Task 0.4 | порог плана |
|---|---|---|---|
| `docs/claude/memory/MEMORY.md` (git blob) | **7 222** | 33 392 (`main~1`); 29 881 (резервная папка Windows) | ≤ 8 192 — **выполнено** |
| Windows-индекс `~/.claude/projects/…/memory/MEMORY.md` | **7 629** | 29 881 (`memory_backup_2026-10-04/MEMORY.md`, 418 файлов в папке) | ≤ 8 КБ — выполнено |
| `.claude/memory/MEMORY.md` (Mac-копия, git) | 8 925 | — | не входит в метрику; > 8 КБ |
| корневой `CLAUDE.md` (git blob) | **26 889** | 25 126 (`main~1`); план называл 25,3 КБ | < 12 288 — **не выполнено**, +1,8 КБ с `main~1` |
| `.claude/CLAUDE.md` (git blob) | **30 099** | 29 568 (`main~1`); план называл 30,0 КБ | < 12 288 — **не выполнено**, +0,5 КБ с `main~1` |
| `~/.claude/CLAUDE.md` (вне репо) | **4 887** | — | вне порога |

- Расхождение `wc -c` рабочего файла и размера blob (27 089 против 26 889 у `CLAUDE.md`) — CRLF в рабочем дереве Windows. Метрикой берётся blob.
- Два корневых `CLAUDE.md` за сутки выросли, а не уменьшились (Task 0.4 трогал только память). Целевое «< 12 КБ» — задача 2.4.
- Загрузка в каждую сессию сейчас: 26 889 + 30 099 + 4 887 + 7 629 (локальная память) ≈ **69,5 КБ**; в O1 было 91,3 КБ (с 29,9 КБ индекса).

## 8. Повторные грабли (новая метрика, решение владельца 2026-10-04)

**Определение.** Урок = файл с `type: feedback` в `docs/claude/memory/*.md` и `docs/claude/memory/_archive/*.md`. «Новый» = дата создания в 2026-08-05 … 2026-10-04. «Повтор» = у урока есть более ранний «родственник» (из пары, слитой в секции `## Слито из` выжившего файла), и этот урок создан **позже** родственника; плюс самоописанный повтор по тексту.

**Команды:**
```
git grep -n "Слито из" -- docs/claude/memory                 # 50 пар найдено разбором; ARCHIVE.md называет 52 (52 влиты)
git log --follow --diff-filter=A --format=%ad --date=short -- <файл> | tail -1     # дата создания (с учётом git mv в _archive)
python plans/2026-10-04_atlas/research/baseline_scripts/m8.py                                       # весь счёт
```
**Окно:** 2026-08-05 … 2026-10-04. **n:** 277 уроков `feedback` (210 в корне памяти + 67 в `_archive`, после слияний), из них **184 новых**; 93 созданы до окна.

**Результат:** **30 из 184 = 16,3 %** новых уроков имеют более раннего «родственника» по слиянию (метод 1). Три урока с самоописанным повтором в тексте — вне этого набора: `feedback_a_control_reproduces_the_defect_it_was_built_to_catch` («один и тот же дефект» Ф5), `feedback_pytest_import_order_hides_a_cycle` («второй раз»), `feedback_named_main_cause_may_be_a_minor_share` («та же ошибка в 3.1»). С ними **33 из 184 = 17,9 %**.

Строго «новый слит в более старый» (дата родственника < даты нового): 12 из 28 слитых новых — **6,5 % от 184**.

Пары (новый → более старый), 30 шт.:

| новый (дата) | более ранний |
|---|---|
| a_absence_assertion_needs_a_reachability_check (09-01) | absence_assertion_under_extra_ignore_is_vacuous |
| a_faithful_fake_still_lacks_the_protocol (09-01) | a_stub_silences_the_names_it_is_read_for; double_must_block_like_the_original; fake_that_always_succeeds_mutes_the_gate |
| a_list_walking_guard_cannot_see_a_removed_item (08-29) | a_guard_that_counts_at_least_once_is_blind |
| coverage_per_check_is_not_coverage_per_claim (09-03) | a_guard_that_counts_at_least_once_is_blind |
| a_guard_that_counts_at_least_once_is_blind (08-26) | guard_threshold_hides_partial_blindness; parametrization_built_from_the_subject_collapses_with_it |
| a_handmade_readback_leaves_its_producer_unguarded (09-02) | a_guard_below_the_claim_guards_the_layer_not_the_claim |
| a_peer_session_shares_the_tree (08-31) | shared_tree_makes_injections_look_like_flakes; worktree_for_parallel_samefile; git_stash_pop_wrong_stash |
| diagnose_live_system_with_backend_ctl (08-11) | backend_ctl_for_agents |
| bash_heredoc_collapses_backslashes (09-29) | bash_tool_unbalanced_quote_breaks_command |
| commit_takes_the_whole_index (08-10) | commit_msg_format |
| precommit_rollback_drops_unstaged_edits (08-14) | commit_takes_the_whole_index |
| explicit_model_per_agent_role (10-02) | model_split_impl_vs_review |
| fakes_feed_config_flat_so_key_address_defects_are_invisible (08-19) | config_delivery_shape_differs |
| injection_zero_may_mean_the_guards_were_not_collected (08-24) | a_zero_under_injection_has_three_readings; broken_injection_is_not_a_vacuous_test; injection_base_needs_a_collected_count; zero_reds_can_mean_a_useless_layer |
| an_injection_must_prove_its_axis_is_live (09-06) | injection_zero_may_mean_the_guards_were_not_collected |
| inject_only_after_the_work_is_committed (08-20) | injection_rollback_by_restore_not_replace |
| pydantic_assignment_keeps_rejected_value (10-02) | model_copy_does_not_validate |
| a_hook_that_writes_a_shared_file_deadlocks_two_writers (09-08) | precommit_stash_collision_2plus_agents |
| property_unchecked_at_the_second_party (08-16) | one_door_two_roads_needs_two_guards |
| qex_full_rebuild_runbook (10-02) | qex_reindex_budget |
| qt_mcp_flag_value_is_compared_verbatim (08-12) | qt_mcp_always_probe |
| recipe_knob_must_be_named_in_from_recipe (08-12) | read_the_key_from_the_section_already_travelling |
| stepwise_statement_needs_draining (08-11) | sqlite_pragma_fails_silently |
| test_setting_one_handle_of_a_pair_measures_priority (08-10) | test_params_hide_defect_window |
| test_values_near_defaults_test_the_default (08-06) | test_params_hide_defect_window |
| test_reddens_only_under_a_paired_injection (08-14) | two_safeguards_hide_which_one_holds |
| a_lock_patch_can_hang_the_exit_not_the_test (09-03) | test_survived_its_own_break |
| the_plans_stated_cause_is_a_hypothesis (08-31) | plan_spec_can_lie |
| zero_observations_looks_like_a_result (08-24) | silent_detector_proves_nothing |
| zone_guard_never_closes_the_class (08-11) | tests_invisible_to_testpaths |

(все имена с префиксом `feedback_`; 3 пары с одинаковой датой создания исключены как неоднозначные.)

**Kill №6:** повтор метрики в K1.1 тем же скриптом; «не снизилась» = доля ≥ 16,3 %. Окно K1.1 будет короче и с меньшим n; сравнивать долю, не счёт.

**Слабости метода (все существенные):**
1. **Круговая причина.** Слияния сделал агент Task 0.4 сегодня по сходству. Метрика «был похожий урок» наследует его критерий сходства. Пары — суждение, не факт.
2. **Дата создания ≠ дата события.** `git log --diff-filter=A` даёт дату первого коммита файла в `docs/claude/memory`; урок мог быть написан в Windows-памяти раньше и перенесён dual-write позже. Распределение дат не склеено в одну дату (топ-день 2026-08-11 — 20 файлов), но сдвиг на дни возможен.
3. **Репозиторий видит часть уроков.** В git — 277 `feedback`; в Windows-памяти до 0.4 было 418 файлов. Нетрекаемые уроки не учтены.
4. **Родственник ≠ тот же сбой.** Слияние по теме («инъекции», «тестовые подделки») поднимает долю: общий класс дефекта считается повтором. И наоборот: настоящий повтор без слияния (урок записан заново, слит не был) не виден.
5. **Фразы** («снова», «ещё раз», «повтор») дают мало: 14 попаданий на 184 файла, 3 из них признаны повтором вручную. Большая часть — «снова» в техническом смысле.
6. **«Повтор» в смысле владельца** («урок был, но не сработал») требует доказать, что **агент повторил ошибку после чтения урока**. Этого метод не показывает: он видит только сходство текстов. Прямая проверка — транскрипты: сработала ли подсказка карточки/`pack` до повтора. Станет возможна после появления `atlas log`.

---

## Что осталось открытым / ненадёжно в моей работе

- П. 3 и п. 8 — текстовый майнинг с суждением; числа даны для тренда, не для вердикта.
- П. 1 меряет «имя названо в тестах», а не «гарантия доказана»; Protocol-имена занижают долю.
- П. 4 — свой скрипт вместо `agent_report.py` (которого нет); «первая правка» не отделяет правку задачи от записи в scratchpad.
- П. 6 — подбор фраз мой; числа «мест» зависят от формулировки и исключений.
- Окно п. 4 — 30 дней (транскрипты старше 2026-09-04 отсутствуют), а не 60.
- Вопрос владельцу (в `OPEN_QUESTIONS.md`, если решит лид): ссылки на `scripts/agent_report.py --live` в `team-protocol/SKILL.md`, `executor-brief.md` и `plan.md` указывают на несуществующий скрипт — писать его или убрать ссылки.
