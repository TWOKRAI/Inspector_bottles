# Handoff map-E1, раунд 2 (developer) — работа не начата в коде, сделан только разбор

Репозиторий: main (D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles), HEAD 1dc6c71b7. Рабочий каталог среды при обрыве сменился на worktree
`.claude/worktrees/atlas-map` (ветка feat/atlas-lookup-map) — **там нет scripts/nav_bench**: мои файлы лежат НЕПОМЕЧЕННЫМИ только в основном
чекауте (`?? scripts/nav_bench/`). Работать там абсолютными путями основного чекаута; не коммитить; реальных `claude` не запускать; править только
`scripts/nav_bench/` (плюс отчёты в `docs/reviews/`).

## Состояние (раунд 1 — готово, 20 тестов зелёные)
Файлы: scripts/nav_bench/{score.py 213, bench.py 559, __init__.py, questions/k0.json, conditions/{source-only,map-only,reference}.json, README.md,
tests/{test_score.py, test_bench.py}}. Отчёт раунда 1: docs/reviews/2026-11-06_task-map-E1-developer.md. Ревью и решения лида (12 находок + новые
условия + пункт 13) сохранены дословно: docs/reviews/2026-11-06_task-map-E1-review.md (выполнено). **Все правки раунда 2 ещё не сделаны** — ни одна
строка кода после раунда 1 не менялась (проверить `diff` не нужно: резервные копии /tmp/*.bak в этой сессии уже не нужны, файлы == раунд 1).

## Что сделано в этой сессии для раунда 2
- `claude --help` (v2.1.289) проверен: **`--tools <tools...>`** есть («из встроенного набора; "" — отключить все»), **`--strict-mcp-config`** есть
  («только серверы из --mcp-config»), `--mcp-config <configs...>` есть, `--setting-sources` есть. Для находки 5 можно ставить `--tools` из allowed_tools
  (технический предел) и `--strict-mcp-config` вместе с `--mcp-config` у MCP-условий.
- `git archive` и `tar` в Git Bash доступны (`git archive <sha> | tar -x -C <dir>`).
- Источники адресов для K0 уже сверены (см. отчёт раунда 1); для находки 4 пути `test_watcher_final_write.py` и `config_module/tools/__init__.py:17`
  уже подтверждены `git grep` на 1dc6c71b7 (оба существуют; `tools/__init__.py:17` = `from .watcher import ConfigFileWatcher`); путь
  `process_module/tests/test_observability_hot_reload.py` существует (строка 4 упоминает ConfigFileWatcher) — для Q6 брать `line: null`.

## Что осталось (по порядку; оценка 40-50 вызовов — поэтому хэндофф)
1. **score.py**: `require: all|any` на вопрос; `tolerance` на запись эталона (по умолчанию 3; Q2 и Q3 = 0); диапазон `path:a-b` попадает, если пересекает
   окно эталона (нужно изменить `parse_location` — сейчас берёт первую строку); потолок `len(expected)+1` адресов (лишние несовпавшие при `sure` =
   ложные); `confidence` через `.strip().casefold()`; `sure` без адресов = miss (документировать); три полосы вердикта PASS/FIX(6–7 попаданий)/FAIL(<6);
   `TAINTED` при любом нарушении доступа; `expected_facts` (`any_of`, casefold-подстрока в тексте ответа, `require` all|any по фактам), отдельный счёт
   `facts_hit`; относительные пороги `calls_ratio_max`, `tokens_ratio_max`, `baseline` (медиана базовой записи, метрика final_context_tokens).
2. **bench.py**: (1) чистая копия: `git archive <repo_sha>` -> `%TEMP%/nav_bench/<sha>_<hash(exclude)>`, удалить `exclude` набора (новое поле набора;
   по умолчанию у k0 — scripts/nav_bench, scripts/atlas/tests, docs/handoffs, docs/reports, docs/reviews, plans, docs/claude/memory), затем скопировать
   context_files условия (из текущего репозитория); `--root` прогона = эта копия, без .git; переиспользовать при совпадении; HEAD-предупреждение
   перейти на проверку исходного репозитория (находка 11: `git status --porcelain -- <expected paths>`). (2) запись на повтор: `tool_calls`,
   `final_context_tokens` (usage последнего assistant-события), `cumulative_tokens` (in+out+cc), `cache_read_tokens`, `subtype`; `is_error` -> `error =
   subtype`; показать в таблице. (3) подкоманда `floor`: один тривиальный вопрос теми же флагами. (4) подкоманда `verify-set`: каждый expected.path
   существует на repo_sha, `symbol` (если задан) встречается в пределах tolerance от строки (`git show`). (5) аудит по allowlist: любой tool_use вне
   allowed_tools и любой Read вне context_files — нарушение; сравнение casefold + нормализованные пути; нарушение -> вердикт TAINTED; `--tools` и
   `--strict-mcp-config` в build_command. (6) fallback final_text: если в `result` ответов меньше, чем вопросов, добавить текст всех assistant-блоков (при
   конфликте побеждает `result`). (7) стоимость: `expected_tokens > 0` обязателен; реальный запуск без `max_budget_usd` отказ, кроме `--no-budget`;
   печатать `repeats × max_budget_usd`. (8) preflight `requires: ["qex-index","graphify-graph"]` + поле `mcp_config` в условии: проверить наличие
   индекса/графа для корня прогона, иначе отказ с точной командой сборки; индексов самому не строить.
3. **Условия**: `grep-read` (переименование source-only, оставить source-only как алиас), `qex` (+ `mcp__qex__search_code`), `graphify` (+ `mcp__graphify__*`
   чтения), `all` (всё, включая reference). Пороги: hits_min 8 + relative ratios (baseline — запись source/grep-read).
4. **k0.json**: добавить `require`, `tolerance`, `exclude`; Q1, Q2, Q4 = `require: all`; Q2/Q3 tolerance 0; Q7 + `config_module/tools/__init__.py:17`;
   Q6 + `test_watcher_final_write.py` + `process_module/tests/test_observability_hot_reload.py` (line null). Q-вопросы с `require: all` и несколькими
   адресами: Q1, Q2, Q4 (по два адреса).
5. **`questions/arch.json`** (пункт 13): 10 архитектурных вопросов (список тем в docs/reviews/2026-11-06_task-map-E1-review.md), repo_sha 1dc6c71b7, exclude как
   у k0; факты проверить `git show`/`git grep` на 1dc6c71b7 и вписать доказательства в отчёт (пункт 6 — счёт импортов `router_module` только `git grep`,
   не из docs/arch-map/model.json). Порог набора: `facts_hit >= 8` из 10.
6. **Тесты** (новые, литералы): last-id-wins, final_text fallback, require all/any по адресам и по фактам, facts any_of casefold, диапазон адресов,
   потолок адресов, tolerance 0, TAINTED, подкоманда floor/verify-set на двойниках, чистая копия (в копии нет excluded-путей и .git), отказ без
   max_budget_usd, preflight. Обновить README (русский): чистая копия, условия, TAINTED, полосы вердикта, факты.
7. **Инъекции после правок** (прогноз назвать ДО запуска, наблюдать после): убрать `require: all`; убрать исключение путей при копировании; выключить
   TAINTED. Назвать красные тесты.
8. **Отчёт**: раздел «Раунд 2» в docs/reviews/2026-11-06_task-map-E1-developer.md (<= 25 строк в финальном сообщении), в нём доказательства фактов arch.json.

## Ловушки
- Среда: `PYTHONUTF8=1`; `.venv/Scripts/python`; тесты: `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light inspector-bottles-32 .venv/Scripts/python -m pytest scripts/nav_bench/tests -q --tb=short -p no:cacheprovider` из основного чекаута (в worktree `git-common-dir` указывает на основной — но тесты и файлы живут в основном).
- ruff strip: импорт и использование — одной правкой; ruff format перестроил bench.py (номера строк в раунде 1 устарели; читать файл заново).
- Хук SubagentStop падал на `scripts/arch_map/build.py` (contract-lite) — это чужой файл, к nav_bench не относится.
