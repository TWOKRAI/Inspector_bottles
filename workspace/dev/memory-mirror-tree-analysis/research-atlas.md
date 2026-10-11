# Отчёт исследователя: Atlas и «зеркальное дерево памяти»

Источник: агент `investigator` (Opus, только чтение), прогон 2026-10-11. Текст — отчёт агента; ссылки `файл:строка` даны на состояние репозитория в тот день.
Сопоставление с планом Atlas и выводы — в `../memory-mirror-tree.md`, раздел 3A.

## 1. Что такое Atlas
- **Цель.** Реестр доказанности строится из git, планов, `modules.yaml` и кода. В git его не кладут: «реестр — производная, её не коммитит никто» (`plans/2026-10-04_atlas/plan.md:52`). У реестра два «лица»: CLI для агента и HTML для владельца (`plan.md:41-42`).
- **«Карточка» — не хранимая сущность.** Это вывод команды `atlas card <module>`: список строк, собранный из БД и git (`scripts/atlas/views.py:1-8`). Хранимые сущности — `Node{kind,id,path,status,time}`, ключ `kind:id` (`scripts/atlas/schema.py:16-24`). Ещё есть `Edge{kind,src,dst,via}` и `Finding{code,severity,node,detail,...}`.
- **Виды узлов** (`scripts/atlas/DECISIONS.md:41-54`): module, plan, task, commit, doc, interface, guarantee, test, injection, result, handoff, **lesson**.
- **База.** SQLite `data/atlas.sqlite`, файл в `.gitignore` (`.gitignore:133`). Таблицы: builds, nodes, edges, findings, snapshots, view_cache (`scripts/atlas/store.py:30-48`). База — кэш: при смене версии схемы таблицы пересоздаются, миграций нет (`store.py:49`). Сборка кэшируется по ключу (sha, main_ref, отпечаток адаптеров) (`scripts/atlas/build.py:51-73`).
- **Команды:** `build`, `check`, `card`, `pack`, `ref`, `index [--write|--check]`, `log`, `lint-result`, `--json` (`scripts/atlas/__main__.py:43-58`).
- **Адаптеры** (`build.py:28`): `modules` — узлы module из `modules.yaml` (`adapters/modules.py:52`); `plans` — plan и task через `plans_progress --json`, плюс находка RESULT_FORM (`adapters/plans.py:1-6`); `commits` — узлы commit, рёбра refs/implements/touches/done_by, находки DONE_* и REF_* (`adapters/commits.py:1-9`); `code` — interface и test, находки INTERFACE_WITHOUT_TEST и PRE_POST_MISSING (`adapters/code.py:1-5`); `rules` — правила П1–П4 по AST (`scripts/atlas/rules.py:1-6`).
- **Сделано (DONE).** Phase 0 (0.1–0.8), P1.1, 1.1, 1.2, 1.3a, 1.6e, 1.7a, 1.9a, 1.9d (`plan.md:140-186`). По коду в main и итогам задач сделаны также 1.3b, 1.3c, 1.5a, 1.6, 1.6b, 1.6c: адаптеры на месте, `docs/atlas/INDEX.md` существует, итог 1.6c начинается словами «STATUS: DONE». При этом в `plan.md:164-174` эти задачи всё ещё значатся `[PENDING]`: статусы плана отстали.
- **В работе и впереди.** 2.4 — IN PROGRESS (`plan.md:212`). До K0b: 1.6g, 1.9b, 1.9c, 1.9e, 1.10a, 1.10b, 1.10e, 1.9f, затем сам K0b (`plan.md:185-194`). После K0b: 1.7b, 1.6d, 1.10c, 1.10d, 1.7c (`plan.md:198-202`). Заморожены (DEFERRED): 1.4, 1.5b, 1.8 (`plan.md:166,168,172`). Далее: Phase 2–5 и K1.1.

## 2. Что Atlas уже делает для памяти
- **2.4g сделана** (`plans/2026-10-04_atlas/tasks/2.4g.result.md:7-13`): есть `scripts/memory/{_lessons,tags,search}.py`; `TAGS.yaml` — 30 механизмов; 251 урок канона перетеган, 113 уроков ролей перенесены в канон.
- **Правила тегов.** `module:` ⊆ id из `modules.yaml`, `mechanism:` ⊆ `TAGS.yaml` (`tasks/2.4g.md:37-39`). Проверку `tags.py --check` вызывает `validate.py` (коммит `74353b59f`). Исследователь запустил `tags.py --check`: выход 0.
- **Индекс не хранится**, строки собираются при запросе (Р1, `2.4g.md:34-36`). Субагенты уроков не пишут: они отдают блок `MEMORY LESSON` (Р5, `2.4g.md:47-57`).
- **`apply_2.4g.py`** — одноразовый: применяет TSV, делает `git mv`, правит только frontmatter (`research/memory/apply_2.4g.py:1-12`). CRAFT-разбивка — пять дайджестов, в том числе `CRAFT-by-module.md` (99 строк, группы по `module:`).
- **Привязка к путям есть, но косвенная.** Урок → модуль (через `module:`) → `paths` в `modules.yaml`; путь → модуль даёт `scripts/atlas/modules.py:67-79` (выигрывает самый длинный префикс).
  - Тезис черновика «`module:` — НЕ пути» был неточен: `tools/backend_ctl` → `backend_ctl/` (`modules.yaml:805-808`), `scripts` → `scripts/` (`modules.yaml:836-839`). Сопоставление однозначное, но грубое.
- **Адаптера памяти в коде нет.** `git grep lesson` в `scripts/atlas` находит только `DECISIONS.md`. В ADR он только заложен: узел `lesson`, id = имя файла (`DECISIONS.md:54`), ребро `about` lesson→module (`:84`). Урок только с `mechanism:` остаётся узлом без рёбер (`:56`).
- **В планах:** 1.10c — «Уроки (N)» в `card` (`plan.md:200`), то есть pull. В карточке — «уроки по модулю … из frontmatter» (`research/CTO_VERDICT.md:116`).
- **Числа на сегодня:** уроков 379, с `module:` — 225, разных значений `module:` — 54. Больше всего у process_module (36), tools/backend_ctl (26) и logger_module (26). Подсчёт — grep исследователя (позже парсером `_lessons`: 371 урок, 224 с `module:`).

## 3. Привязка к коду и свежесть: что переиспользовать
- **Свежесть в Atlas** — число содержательных коммитов в зоне документа (без массовых правок больше 30 файлов и без `style`), а не штамп и не дата (`plan.md:54`). Возраст выводится из git, без записи в файл (`research/O3_git_freshness.md:173`, вариант B′). Адаптер docs и находка DOC_STALE отложены до 1.4 (`plan.md:166`).
- **Хешей содержимого и якорей на символ или строку в Atlas нет.** Ключи — только SHA сборки и отпечатки (`build.py:33-48`).
- **Что взять для `check` и `sync`:** (а) `check._renames` — `git diff -M --name-status` даёт пары old→new (`scripts/atlas/check.py:42-62`); (б) `modules.resolve` (`modules.py:67`); (в) чтение по ревизии через `Tree` (`scripts/atlas/tree.py`); (г) модель находок и храповик базы (ADR-ATL-002, `DECISIONS.md:172+`); (д) `REF_MOVED` / `REF_TO_MISSING` как образец «висячей ссылки» (`DECISIONS.md:100-101`).
- **Проверка «символ исчез».** В Atlas её можно сделать через griffe/grimp в `codemap.py`, но это дорого: первый `card` занимает 8,3–9,9 с (`plan.md:185`). Для якорей дешевле `git grep -w` — предложение исследователя, не замер.

## 4. Пересечения с черновиком дерева
- **(а) Адресация.** У Atlas id урока = имя файла (`DECISIONS.md:54`); у черновика — `L-<область>-<номер>`. Дублирование: два id на один урок. Atlas отклонил узел `file` («6,8 тыс. файлов», `DECISIONS.md:165`), единица у него — модуль (`plan.md:142`); узел на файл в черновике — конфликт уровня детализации.
- **(б) Хранение.** В обоих случаях истина — файлы в git. У Atlas БД производная (`plan.md:52`). Черновик хотел перенести уроки в `.claude/rules/memory/`; Atlas такого не требует. Конфликта нет, если источник истины остаётся в `docs/claude/memory/`.
- **(в) Доставка.** Atlas — только pull: CLI, `pack` в брифе по требованию `lint-brief` (`plan.md:97`), MCP-сервер 1.10e тоже pull (`plan.md:192`). В 1.10b хук SessionStart лишь печатает ревизию, а PostToolUse ведёт журнал (`plan.md:191`). Push по `paths:` в Atlas нет — черновик дополняет.
- **(г) check / sync / устаревание.** Atlas даёт rename-следование, находки и храповик. Черновику нужен только узкий `check` якорей. Риск дублирования, если писать свой отдельный `mem_tree check`.
- **(д) Индексы.** Прецедент генерации есть: `INDEX.md` — «собран командой …, руками не править» (`docs/atlas/INDEX.md:1`), с `index --check` (`__main__.py:52-54`). Хранимый индекс памяти 2.4g отвергла (Р1) — генерировать нужно только узлы доставки.

## 5. Три варианта объединения
- **A. Урок — узел Atlas, слой `.claude/rules` генерируется из БД.** Берём: узел `lesson` и ребро `about` (уже в ADR), `index --write/--check` как образец. Строим: адаптер lessons и генератор. Риск: доставка зависит от ядра Atlas (вероятность kill 40–50 %, `plan.md:98`; холодная сборка ≤ 5 с, `plan.md:169`); адаптер выпадает из очереди (1.4 заморожена).
- **B. Дерево независимо, Atlas его только читает.** Строим: зеркальное дерево, `mem_tree` (4 команды), миграцию 380 + 185 файлов, id `L-*`. Слоёв: +1 дерево и +1 схема id рядом с 2.4g. Риски: противоречит отказу ADR от узла на файл; два `check`; вторая копия. Объём самый большой.
- **C. Без дерева: в Atlas добавить push.** Push пришлось бы строить на хуках — то, что Claude Code уже делает сам через `paths:`. Риск: K0b ещё может заморозить Atlas (`plan.md:194`).
- **Рекомендация исследователя — «A-lite»:** источник истины остаётся плоским `docs/claude/memory/*.md`, id = имя файла; во frontmatter необязательные `paths:` и `anchors:`; генератор рядом с `tags.py` и `search.py` читает тем же парсером `_lessons` и пути модулей из `modules.yaml`, без БД Atlas; на каждый модуль пишет `.claude/rules/memory/<module>.md` с указателями «путь — description»; режим `--check` в `validate.py`; 1.10c читает тот же frontmatter. Меньше всего слоёв; слой не зависит от выживания ядра Atlas; при отказе `paths:` деградация до сегодняшнего `search.py`. (Ревью Opus позже убрало `anchors:` и `resolve`: итог — «A-lite-min».)

## 6. Что может столкнуться по срокам
- **Kill №6 — «повторные грабли»** (`plan.md:126`) — та же метрика, которую двигает наша затея. Нужен совместный план замера. (Ревью: Atlas уроки пока не доставляет, искажать нечего; нужна атрибуция — строка в план Atlas с датой и SHA слияния.)
- **1.10d добавит строки в `modules.yaml`** `scripts/{atlas,...,memory}` (`plan.md:201`). (Ревью: адрес доставки `module: scripts` не меняется; меняется только `card`.)
- **R5 открыт:** у `.rules/*` нет загрузчика, перенос в `.claude/rules/` не решён (`research/rules_map_24a.md:221`; вне скоупа — `tasks/2.4.md:99`). Это тот же механизм — решать вместе, отдельной правкой позже.
- **1.10b (SessionStart и PostToolUse-журнал)** пересекается с `report` черновика (`:101`).
- **Бюджет облака** — до 2026-11-04 (`plan.md:70`). Открытые вопросы плана — `plan.md:242-251`, в том числе хвост 0.4 про orphan в `memory_lint` (`:246`).

## Что осталось открытым или ненадёжным (по отчёту агента)
- Статусы `plan.md` для 1.3b–1.6c отстают от кода. DONE исследователь заключил по файлам и коммитам, а не по `plans_progress --json` — его не запускал.
- `atlas card` и `build` не запускал. Время и вывод взяты из плана, не воспроизведены.
- Числа по `module:` — grep по строкам frontmatter. Ключи под `metadata:` и многострочные значения могли посчитаться неточно; точный разбор даёт `_lessons`.
- Не проверены объём узла на модуль в токенах (у process_module 36 строк описаний) и поведение `paths:` в worktree.
- Прочитаны выборочно, а не целиком: `CONSOLIDATED.md`, `ACTIONS.tsv`, `MEMORY.new.md`, `O2_backbone.md`, `CLOUD.md`, хендоффы 10-05 и cloud-pilot.
- «A-lite» — рекомендация исследователя, без вердикта CTO.
- Эскалация исследователя к CTO («внедрять A-lite до K1.1 или после?») разобрана ревью Opus: до K1.1, CTO звать не нужно (`../memory-mirror-tree-review.md`).
