# Task 1.1, ревью кода `scripts/nav_bench/` на `930c5f2a3` — reviewer на sonnet

ВЕРДИКТ: CHANGES REQUESTED (5 находок)

Объект: `scripts/nav_bench/` на SHA `930c5f2a3`, прочитан через `git archive` в `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/8a345e65-b3c1-49f2-8202-27b0200f24c9/scratchpad/nb-review`. Рабочую копию `feat/arch-map` не читал, ветки не переключал. Ничего не правил, не коммитил. Живой `claude` не запускал.
memory hits: `search.py benchmark answer key clean copy` -> релевантных уроков нет (ближайший: `feedback_an_inventory_grep_needs_fixed_strings.md`).

## Что запускал (команда -> результат)

- Тесты через ворота (`machine_gate.sh light inspector-bottles-e6 python -m pytest scripts/nav_bench/tests -q --tb=short -p no:cacheprovider`, `PYTHONUTF8=1`): `36 passed in 0.25s`. Ворота переклассифицировали light -> medium и пропустили (код не 75). Прогноз задачи (36+) сошёлся.
- `bench.py verify-set` на k0: `проверено записей 23, проблем 0`. На arch: `проверено записей 27, проблем 0`. Проверено только то, что файл и символ на месте и строка evidence есть. Верность самих фактов verify-set не проверяет.
- Инъекции на одноразовых копиях в `.../scratchpad/inj/`. Все пять совпали с прогнозом:
  - И1 (убрать `require: all` в `score.py`): красный только `test_require_all_needs_every_expected`.
  - И2 (убрать исключение путей в `prepare_clean_copy`): красный только `test_clean_copy_excludes_answer_paths`.
  - И3 (выключить `TAINTED`): красный только `test_violation_makes_verdict_tainted`.
  - И4 (побеждает первый id): красные `test_last_answer_id_wins` и `test_final_text_fallback_and_budget_subtype_visible`.
  - И5 (игнорировать базу в `summarize_record`): `36 passed`. Ни один тест не ловит потерю `--baseline` (см. находку 3).
- Скрипты воспроизведения (мои, вне репозитория): `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/8a345e65-b3c1-49f2-8202-27b0200f24c9/scratchpad/repro/{repro.py,inject.py,echo.py,leak.py}`.

## Находки раунда 1 (12) и пункт 13

| # | Статус | Воспроизведение (вход -> результат, путь:строка) |
|---|---|---|
| 1 Ключ ответов виден | закрыто (побочный эффект -> находка 2) | Копия `git archive 1dc6c71b7` без `exclude`: `bench.py:213-219`, путь строится `tempfile.gettempdir()` (`bench.py:157`). `git grep` по `1dc6c71b7` вне 7 исключённых путей на `k0_reference`, `k0_targets`, `test_exam_k0`, `nav_bench`, `observability_reload.py:2305`, `router_manager.py:130`: 0 совпадений. `.git` в копии нет (тест). И2 красная. |
| 2 База несравнима | закрыто, дыра -> находка 3 | Четыре метрики пишутся в `bench.py:615-619`; `test_fake_session_end_to_end` проверяет 850 / 1500 / 99999. `floor` есть (`bench.py:821`, тест). Относительный порог работает: см. (в) ниже. |
| 3 Попадание слишком мягкое | нет -> находка 1 | `require: all` у Q1, Q2, Q4 и `tolerance: 0` у Q2, Q3 есть (`k0.json`), полосы PASS/FIX/FAIL проверены тестом, И1 красная. Потолок адресов обрезает список, а не штрафует (находка 1). |
| 4 Верные адреса засчитаны ложными | закрыто | Q7 содержит `config_module/tools/__init__.py:17`, Q6 содержит 3 файла. `verify-set` k0: 0 проблем. |
| 5 Аудит map-only | закрыто | Список разрешённого: `bench.py:558-576`. `TAINTED`: `score.py:311-312`. `--tools`: `bench.py:406`. `--strict-mcp-config`: `bench.py:412`. И3 красная только на своём тесте. Оговорка по Windows-пути: пункт (б). |
| 6 Ответы теряются при коротком `result` | закрыто | `bench.py:580-585`. Тест `test_final_text_fallback...`; И4 его красит. Замечание: условие `>= question_count` считает любые id, не id вопросов набора. |
| 7 Обрыв по бюджету не виден | закрыто | `subtype` в записи, `error = subtype`, колонка «статус» в таблице, вывод в stderr (тест). |
| 8 Оценка стоимости | закрыто | `expected_tokens > 0` (`bench.py:817-819`); отказ без `max_budget_usd` без `--no-budget` (`bench.py:852-856`); строка `repeats x max_budget_usd` (`bench.py:432`). Тест `test_budget_and_cost_guards`. |
| 9 Уверенность | закрыто | `score.py:118-123` (`.strip().casefold()`, неизвестное = `unknown`), документ `score.py:21`. `sure` без адресов = miss (тест). |
| 10 Диапазон `path:a-b` | закрыто | `score.py:108` (пересечение окна), тест `test_range_intersecting_window_is_hit`. |
| 11 Грязные эталонные файлы | закрыто | `git_dirty` `bench.py:247-257`, предупреждение `bench.py:825-832`, тест. |
| 12 Недостающие тесты | закрыто | `test_last_answer_id_wins` (И4 красная), `test_final_text_fallback...`, `test_verify_set_flags...`. На реальных наборах `verify-set` даёт 0 проблем. |
| 13 `arch.json` | нет -> находка 4 | 10 вопросов, у каждого `evidence`, пороги 8/10 на месте, 2 теста фактов есть. Сам вычислил по `git show 1dc6c71b7`: A4 (`__all__` из 6 имён), A5 (17 = 7 своих + 10 у `IBaseManager`), A9 (`_resolve_pipeline` на `launch.py:403`) верны. A6: `git grep` с `[[:space:]]` даёт process_module 14, prototype/frontend 3, frontend_module 3, process_manager_module 2 — ключ верен. Вопрос засчитывается, если ответ содержит подстроку, а не понимание. |

## Три пункта DESIGN

**(а) `parse_session_output` — имена полей из документации.** Подтверждаю: docstring `bench.py:497-499` и `README.md:120` говорят «не проверено живым прогоном». По моему знанию формата имена (`assistant.message.content[].tool_use`, `message.usage`, `result.{subtype,is_error,num_turns,result,usage,total_cost_usd}`) выглядят верно, но это не проверка. Все тестовые потоки пишет `_stream` в `test_bench.py` — тесты доказывают согласие парсера с представлением автора. Опасность не в ошибке, а в тишине: имя поля не совпало -> метрика `None` -> «не измерено» -> `PASS` (находка 3). Реальный сырой вывод первого живого прогона нужно сохранить как фикстуру.

**(б) Чистая копия под `%TEMP%` и Git Bash.** Путь строится `tempfile.gettempdir()` + `Path` (`bench.py:157`), строк Windows нет. `git archive` и `tarfile` вызваны списком аргументов, без shell и внешнего `tar` — от Git Bash копия не зависит. Условия запрещают `Bash`. Остаётся риск: префикс аудита `run_root.resolve()` (`bench.py:874`), а `cwd` сессии — нерезолвленный `run_root` (`bench.py:878`). Если `%TEMP%` в короткой форме `C:\Users\TWOKRA~1\...`, абсолютные `Read` агента не срежутся по префиксу и map-only получит ложный `TAINTED`. Не проверено: нет Windows. Правка: класть в `prefixes` оба вида (`str(run_root)` и `str(run_root.resolve())`) + тест с коротким префиксом.

**(в) Относительные пороги читают базу `--baseline`.** Цепочка работает: `bench.py:810` -> `load_baseline` (`bench.py:652-656`) -> `summarize_record` (`bench.py:646`) -> `score.verdict` (`score.py:293-296`). Сквозной прогон (`repro.py`, 31 вызов против базы 40): с `--baseline` `calls_ratio` = 0.775 при пределе 0.5 -> `FIX`; без `--baseline` -> `PASS` и «не измерено». Тестов на эту цепочку нет (И5 зелёная). Подробности — находка 3.

## Новые находки (ранжированы по шкале: spec -> architecture/tests -> quality)

**1. [spec] `score.py:164-174` — адреса сверх потолка не штрафуются, если нашёлся верный.**
Вход: Q10, `locations = [верный] + 7 чужих`, `confidence: sure`. Результат: `hit`, `false = 0`. Тот же ответ с верным адресом последним (`[x1, x2, верный]`) -> `false`. Решение раунда 1 №3: «лишние несовпавшие адреса считаются ложными при sure». Реализация обрезает список до `len(expected)+1` и игнорирует остальное при попадании. Текст промпта «extra addresses count against you» (`bench.py:77-78`) неверен для попаданий. Шкала даёт `spec` = блокер; практический вес средний, правка в три строки.
Правка: `over = len(locations) > cap`; `hit` только если эталон закрыт и `not over`; иначе `false` при `sure` и (`stray` или `over`), иначе `miss`. Тест: `[верный] + 7 чужих`, sure -> `false`, unsure -> `miss`. Существующий `test_extra_locations_over_cap_are_false` проверяет только верный адрес третьим.

**2. [architecture] `bench.py:152-158` — grep-read, qex и graphify делят один каталог копии; граф graphify загрязняет базовое условие.**
Вход: `clean_copy_path` для `grep-read`, `qex`, `graphify` -> все `1dc6c71b7-a0cbfd2f54` (`repro.py`, блок R3). Ключ — только `exclude` + `context_files`. Предпроверка graphify ждёт `graphify-out/graph.json` внутри этого каталога (`bench.py:362`), а `GRAPH_REPORT.md` — «architecture overview + recommended questions» (`.claude/plugins/mcp-graphify/README.md:36`). После сборки графа `Grep/Glob/Read` в прогонах grep-read и qex видят граф и отчёт. Вся сравнительная таблица условий и пороги `calls_ratio_max` / `tokens_ratio_max` строятся на загрязнённой базе.
Правка: добавить в ключ `condition["name"]` (или `requires` + `mcp_config`). Тест: путь копии grep-read != путь graphify. Старые копии пересоздать.

**3. [tests] `score.py:305` и `bench.py:810-826` — не измеренная метрика не мешает `PASS`; цепочка `--baseline` не покрыта тестом.**
Вход A: пороги `calls_ratio_max` / `tokens_ratio_max` заданы, `--baseline` нет -> `band = PASS`, `pass = True`, `unmeasured = ['calls_ratio','tokens_ratio']`. Вход B: метрики `tool_calls` / `final_context_tokens` равны `None` (имя поля в живом выводе не совпало) -> `band = PASS`. `README.md:~115` и docstring `verdict()` обещают, что не измеренное «не проходит молча». Вход C: И5 (база выброшена из `summarize_record`) -> `36 passed`.
Правка: в `verdict` при непустом `unmeasured` ставить `pass = False` и полосу `UNMEASURED` (`TAINTED` по-прежнему первее). В `run_bench` отказывать (код 2), если в порогах есть ключ `*_ratio_max`, а базы нет. Хранить `set` базы и сверять с текущим набором (`load_baseline` теряет имя набора). Тест: `run_bench(baseline_path=...)` на моих числах (31 вызов / 40 = 0.775 > 0.5 -> `FIX`; без базы -> отказ) — И5 станет красной.

**4. [tests] `score.py:185`, `arch.json` — факты считаются подстрокой; пять из десяти вопросов выполняются без понимания.**
Воспроизведено (`repro.py`, блок R1; `leak.py`):
- A4: ответ «ConfigSection, ConfigManagerConfig, IConfigManager» (3 имени из 6) -> `hit`. `ConfigManager` и `IConfig` — подстроки длинных имён, факта на `Config` нет (заметка в самом `arch.json` признаёт слабость).
- A2: «preprocessor ... GenericProcessApp» -> `hit`, хотя процесс назван неверно (`processor` ⊂ `preprocessor`).
- A3: `Message` ⊂ `MessageAdapter` — факт пустой.
- A6: опция `multiprocess_prototype/frontend` дословно стоит в тексте вопроса (пример «such as»): треть ответа дана даром.
- A10: `send_message` и `differ` стоят в тексте вопроса (`difference`); `queue` и `control_` угадываются.
Текст вопроса целиком как ответ даёт 0 попаданий из 10 (`echo.py`) — худший случай закрыт, но 2-3 вопроса со слабыми фактами сдвигают 6/10 (FIX) в 8/10 (PASS).
Правка: сопоставлять по границам слова (`re.search(r"(?<!\w)" + re.escape(opt) + r"(?!\w)", text, re.I)`); префиксный факт `control_` заменить полным `control_draw`. Переписать факты A6 и A10 так, чтобы ни одна опция не входила в текст своего вопроса. Для A4 запросить число (`6`) и проверять каждое имя целым словом. Тесты: (1) для каждого вопроса ни одна опция факта не входит в его вопрос; (2) таблица обманных ответов (A4 с 3 именами, A2 с `preprocessor`) -> `miss`.

**5. [quality] `README.md:88-125` противоречит коду раунда 2.**
- `README.md:88`: пороги `calls_median_max (20)` / `tokens_median_max (50000)` — в условиях их нет, стоят `calls_ratio_max` / `tokens_ratio_max`.
- `README.md:92-94`: «Поставляются: source-only, map-only, reference» — нет grep-read, qex, graphify, all.
- `README.md:~99-110`: map-only «ограничен советом, а не запретом», нарушения лишь «видны в записи». В коде `--tools Read`, список разрешённого и вердикт `TAINTED`.
- `README.md:112-113`: «в source-only запрет `Read(docs/arch-map/**)` стоит правилом» — такого правила нет ни в одном файле `conditions/`.
Правка: переписать эти абзацы по коду.

## Что я оставил открытым

- Первый мой счёт A6 был неверным: `git grep -E '^\s*...'` на macOS (BSD regex) пропускает отступные импорты и дал 11/2/2/1. Перепроверил с `[[:space:]]`: 14/3/3/2, ключ верен. Находку «A6 не воспроизводится» снял.
- Проверял сам только A4, A5, A6, A9 по `git show` / `git grep`. Для A1, A2, A3, A7, A8, A10 опираюсь на `verify-set`: он доказывает, что строка evidence есть в файле, а не что вывод из неё верен.
- Вопрос A9 прочитан узко (`_resolve_pipeline`, `launch.py:403`) против «где рецепты выбирают топологию» из задания. Второе место — `multiprocess_prototype/frontend/app.py:106` (`_make_recipe_activated_handler`). Решение за лидом.
- `claude --help` и сам `claude` не запускал. Список флагов («v2.1.289») взят из комментария автора, не сверен.
- Подозрение без доказательства: `conditions/mcp/graphify.json` и `all.json` запускают `graphify-mcp <graph.json>`, а в проекте канон — `uvx graphify-mcp serve graphify-out/graph.json` (`.claude/plugins/mcp-graphify/.claude-plugin/plugin.json`, `SETUP_GUIDE.md:85`). Без `serve` сервер, вероятно, не стартует, и под `--strict-mcp-config` условие молча станет grep-read (инструментов graphify просто не будет, нарушений аудит не увидит). Недостающее доказательство: вывод `uvx graphify-mcp --help` и поле `mcp_servers[].status` из события `init` реального потока. Защита: брать статус MCP из `init`, отказывать, если не `connected`.
- Аудит MCP-вызова не смотрит аргумент: `mcp__qex__search_code` с `path` не равным `run_root` (индексы других проектов, в том числе основного репозитория с ключом ответов) не нарушение. `target` уже пишется в `tool_uses`, сравнение добавить дёшево.
- `context_files` копируются из рабочего дерева `--root`, не из `repo_sha` (`bench.py:220-225`). В `main` по варианту А нет `docs/arch-map/`, поэтому `map-only`, `reference`, `all` упадут в `prepare_clean_copy` с `FileNotFoundError` до Task 3.1 / 4.3. Только по чтению кода, не запускал. Нужно решение лида: оставить как есть или пометить в README.
- Распаковка: ошибки `OSError` (например, MAX_PATH на Windows) считаются «пропущено» с предупреждением, а наличие эталонных путей в копии не проверяется (`bench.py:181-182`). Не проверено: нет Windows.
- Полоса `FIX` в `repro.py` (R5) возникла при выполненных `hits` и проваленном `calls_ratio`. Это расходится с определением CTO «FIX = 6-7 попаданий»; правки не требую, но стоит записать в README.
