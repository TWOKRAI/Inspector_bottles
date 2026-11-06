# map-E1 — nav_bench: отчёт developer

STATUS: DONE (код, набор K0, три условия, README, тесты зелёные; реальных запусков `claude` не было — по брифу)

Репозиторий main = 1dc6c71b7. Коммита нет, `git add` не делался. Новое лежит только в `scripts/nav_bench/` (`??`),
плюс этот отчёт.

## Файлы и строки

| файл | строк |
|---|---|
| scripts/nav_bench/score.py | 213 |
| scripts/nav_bench/bench.py | 559 |
| scripts/nav_bench/__init__.py | 0 |
| scripts/nav_bench/questions/k0.json | 106 |
| scripts/nav_bench/conditions/source-only.json / map-only.json / reference.json | 12 / 13 / 12 |
| scripts/nav_bench/README.md | 142 |
| scripts/nav_bench/tests/test_score.py | 91 |
| scripts/nav_bench/tests/test_bench.py | 293 |

Все 10 REDS из брифа есть под теми же именами (6 в test_score, 4 в test_bench), плюс 10 дополнительных тестов
(CLI dry-run, HEAD-предупреждение, литералы флагов, JSON-вывод без вызовов, упавшая сессия, аудит map-only,
`over_max_turns`, боевой `subprocess_runner` на stdin, загрузка K0, абсолютные пути). `ruff check` и `ruff format --check`
чисты.

## Флаги `claude` (v2.1.289, `claude --help`)

Проверены по `--help`: `-p`, `--output-format` (text|json|stream-json), `--model`, `--allowedTools`, `--disallowedTools`,
`--append-system-prompt`, `--max-budget-usd`, `--no-session-persistence`, `--verbose`.
**`--max-turns` в `--help` НЕТ.** Не передаётся; `max_turns` условия проверяется после прогона по `num_turns`
(поле `over_max_turns`), жёсткий стоп-кран — `max_budget_usd` (добавлен в условия, его не было в схеме брифа).
Набор флагов — одна функция `build_command` и константы вверху `bench.py`.
Имена полей вывода (`num_turns`, `duration_ms`, `result`, `usage.*`, `total_cost_usd`, блоки `tool_use`) — по документации,
**не проверено живым прогоном**.

## Эталон K0: сверка с кодом (`git show 1dc6c71b7:<path>`, строки напечатаны)

Все 20 адресов найдены, ни одна строка не неверна:
Q1 `router_module/interfaces.py:21` (`class IRouterManager(ABC)`), `core/router_manager.py:130` (`class RouterManager(ChannelRoutingManager)`);
Q2 `config_module/interfaces.py:20`, `core/config.py:27`; Q3 `interfaces.py:17` (`def __call__`; класс на :14);
Q4 `interfaces.py:70`, `base_manager/interfaces.py:28`; Q5 `tools/watcher.py:196`, `:38`; Q6 `tests/test_watcher.py` (строка null);
Q7 `observability_reload.py:92, :2305, :2341`; Q10 `data_schema_module/serialization/converter.py:292`.

Поправки и уточнения к handoff:
- `converter.py:291-293` в handoff без пути: в дереве два `converter.py` (framework `data_schema_module` и
  `Services/hikvision_camera/core`). Строки 291-293 верны для framework-файла (`mkdir` :291, `open(path,"w")` :292,
  `write` :293), `save_to_file` :255. Эталон — :292.
- Q4: по исходнику 17 = 7 своих (`interfaces.py:73-104`) + 10 у `IBaseManager` (`base_manager/interfaces.py:39-103`, пересчитано
  по `@abstractmethod` в строках до класса `IBaseAdapter`). Это совпадает с handoff; бриф 1.1 («7 из 16», «9 унаследованных»)
  расходится — по исходнику прав handoff.
- Q5 (частичный): расставлен по исходнику — класс :196 и обработчик `_ConfigReloadHandler` :38.
- Q6 (частичный): сам файл `test_watcher.py`, `line: null`; ответ файловый.
- Q8 (частичный, неоценивается): `start_observability_watcher` определён `observability_reload.py:2259`; вызовы
  `app_module/orchestrator.py:184` (файл по ключу конфига `observability_config_path`) и `:241` (`companion_path()`, спутник рецепта).
- Q9 (частичный, неоценивается): писатель спутника — `observability_companion.py:100` (`write_companion`, tmp + `os.replace`),
  `:256` (`persist_session_to_companion`), вызов `commands/builtin_commands.py:3153`. Другие писатели (например GUI-save
  человеческого рецепта) не искались.
- Q7: ре-экспорт `config_module/tools/__init__.py:17` в эталон не включён (как в handoff), указан в `note`.
  Тестовые потребители watcher'а (`test_watcher*.py`, `test_observability_hot_reload.py`, `app_module/tests`) — вне вопроса «production».

## Тесты

Команда: `machine_gate.sh light inspector-bottles-32 .venv/Scripts/python -m pytest scripts/nav_bench/tests -q --tb=short -p no:cacheprovider`
(гейт переклассифицировал light -> medium и пропустил команду).
Результат: `======================= 20 passed, 2 warnings in 6.20s ========================` (повторно после восстановления: `20 passed in 2.60s`).
Предупреждения посторонние (hypothesis, legacy_sync).

## Инъекции (прогноз назван до запуска — но только в моих рассуждениях, лид проверить это не может)

| инъекция | прогноз красных | наблюдено |
|---|---|---|
| убрать допуск ±3 (`<= tolerance` -> `== 0`, score.py:76) | `test_hit_within_three_lines_miss_at_four`, `test_absolute_path_prefix_is_stripped`, `test_fake_session_end_to_end_writes_counts` (Q1 с :22 при эталоне :21) | ровно эти 3 из 20 |
| убрать защиту `--yes` (`if not yes:` -> `if False:`, bench.py:468) | `test_real_run_refused_without_yes` | ровно он, 1 из 20 |
| (доп.) в токены добавить `cache_read_input_tokens` | `test_fake_session_end_to_end_writes_counts` | ровно он |

Файлы после инъекций восстановлены из копий, `diff` — идентичны.

## Dry-run (приёмка)

`python scripts/nav_bench/bench.py run --questions scripts/nav_bench/questions/k0.json --condition scripts/nav_bench/conditions/source-only.json --repeats 3 --dry-run`:

```
Оценка стоимости: 3 x 85000 = 255000 токенов (ориентир из условия, не счёт)
[dry-run] повтор 1: claude -p --output-format stream-json --verbose --model haiku --no-session-persistence --allowedTools Read,Grep,Glob --disallowedTools 'Bash,Edit,Write,NotebookEdit,Agent,WebFetch,WebSearch,Read(docs/arch-map/**)' --max-budget-usd 1.0 --append-system-prompt '...'
```
(повторы 2 и 3 идентичны; затем печатается промпт, 2077 символов, через stdin). Предупреждения о HEAD нет (HEAD = 1dc6c71b7).

## What I interpreted rather than followed

1. **`--max-turns` не передаётся** (нет в `--help`); добавил необязательный `max_budget_usd` как стоп-кран и поле `over_max_turns`.
2. **Формат вывода по умолчанию `stream-json`, не `json`:** `json` не перечисляет вызовы инструментов, а метрика «вызовы» из брифа
   без этого не измерима. Парсер понимает оба; при `json` число вызовов = `None` и вердикт помечает его «не измерено».
3. **Определение «токенов»** = input + output + cache_creation, без cache_read. В брифе определения нет.
4. **Вердикт по повторам:** hits — худший повтор (min), false — худший (max), вызовы и токены — медиана. Бриф говорит «median» только про вызовы.
5. **`false` в порогах — только на оцениваемых вопросах**; по всем вопросам — в «итогах».
6. **Любой адрес из `expected` достаточен для hit**; Q7 с тремя адресами засчитывается по одному найденному.
7. **Тексты вопросов K0 написал сам** (на английском: агентский промпт): точной формулировки из брифов разведчиков в репозитории нет, в handoff
   только сокращения таблицы.
8. **`map-only` — частично совет:** `Read` нельзя ограничить тремя файлами правилами (deny перекрывает allow), поэтому добавлен аудит чтений
   (`audit_reads`, `violations`) — не в брифе.
9. Условие `reference`: разрешил `Read/Grep/Glob` по коду (справка плюс проверка), а не только справку — бриф этого не уточняет.
10. Промпт передаётся через stdin, не аргументом (длина, кавычки); запись не затирается — суффикс `_2`; сообщение «DESIGN/FILES» вверх не слал
    (правка не под `src/`).

## What I left open / unreliable

- **Ни один живой запуск `claude` не выполнялся**: имена полей вывода, `stream-json` с `--verbose` под `-p`, поведение `--allowedTools`/`--disallowedTools`
  (включая запрет `Read(docs/arch-map/**)` на Grep/Glob) не проверены. Тесты идут на двойниках и на сделанных мной образцах вывода; если реальная схема
  другая, пройдёт всё зелёным, а парсер вернёт пустые счётчики. Настоящая проверка — один дешёвый повтор с `--yes` (решает лид).
- `expected_tokens`: 85000 и 105000 взяты из handoff (пробы Haiku), 60000 у `reference` — моя догадка; порог 50000 токенов может быть несопоставим
  с моим определением «токенов» (нет cache_read; системный промпт Claude Code ~20k+ входит в cache_creation).
- Сессия в каталоге репозитория подхватывает `CLAUDE.md`/память проекта — общий для условий сдвиг; `--bare` не использован (нужен API-ключ).
- `map-only` технически не запрещает чтение кода (только аудит после прогона); версия `claude` в запись не пишется.
- Эталоны Q8/Q9 неполны (см. выше); Q3/Q4/Q6/Q10 — «смысл» ответа (число, поведения, in-place) оценкой по адресу не проверяется.
- Тест `subprocess_runner` использует интерпретатор вместо `claude`; пути с `D:`-диском и обратными слэшами проверены только на Windows.
- Блайнд-тестера не было (решение лида); независимого взгляда на тесты нет.

## Память

memory hits: `scripts/memory/search.py nav bench agent questions` -> ни одного релевантного уроку (8 совпадений по слову agent: про фоновые
цепочки, пиры, окно стенда и т.п.) | none relevant.

MEMORY LESSON | none

## Раунд 2 (ревью стадии 5: 12 находок, пункт 13, MCP-условия)

STATUS: DONE (код, наборы, условия, README, тесты); реальных запусков `claude` не было.

Тесты: `machine_gate.sh light ... pytest scripts/nav_bench/tests` (гейт переклассифицировал в medium, прошёл): `36 passed, 2 warnings`.
`ruff check` и `ruff format` чисты. Коммита нет, `git add` не делался.
verify-set: `k0 @ 1dc6c71b7: проверено записей 23, проблем 0`; `arch @ 1dc6c71b7: проверено записей 27, проблем 0`
(первый прогон arch нашёл реальную ошибку моего evidence A6 — файл без строки `router_module`; исправлено).
Dry-run `grep-read`, 3 повтора: путь копии `C:\Users\INNOTECH\AppData\Local\Temp\nav_bench\1dc6c71b7-a0cbfd2f54`, строки
`Оценка стоимости: 3 x 85000 = 255000 токенов` и `Потолок бюджета: 3 x 1.0 = 3 USD (max_budget_usd на повтор)`.

### Находки
1 clean copy: сделано (`prepare_clean_copy`: git archive + exclude + context_files, без .git, переиспользование; тест на настоящем git-репозитории).
2 метрики: сделано (tool_calls, final_context_tokens, cumulative_tokens, cache_read_tokens, subtype; ratios к `--baseline`; `bench.py floor`).
3 require/tolerance/потолок/полосы: сделано (PASS/FIX/FAIL + TAINTED). 4: добавлены адреса Q6 (2 файла), Q7 (`tools/__init__.py:17`).
5 allowlist-аудит, casefold, TAINTED, `--tools`, `--strict-mcp-config`: сделано. 6 fallback final_text: сделано (result побеждает).
7 subtype/is_error видны (таблица, stderr): сделано. 8 expected_tokens > 0, отказ без max_budget_usd, `повторы x бюджет`: сделано.
9 confidence casefold, sure+пусто = miss: сделано. 10 диапазоны: сделано. 11 предупреждение о грязных эталонных путях: сделано (`git status --porcelain`).
12 тесты last-id-wins, fallback, `verify-set`: сделано. 13 факты (`expected_facts`, `facts_require`, `facts_hit`) и `questions/arch.json`: сделано.
NEW условия `grep-read` (+алиас `source-only`), `qex`, `graphify`, `all`, `mcp_config` + `requires`-предпроверка с точной командой: сделано.

### Доказательства фактов arch.json (`git show`/`git grep` на 1dc6c71b7; в наборе — поле `evidence`, его проверяет verify-set)
- A1 `.sentrux/rules.toml`: «Направление импортов: app → Plugins → Services → framework. Обратные импорты запрещены.»
- A2 `inspection_full.yaml`: `process_name: processor`, `process_class: ...generic_process_app.GenericProcessApp`, плагин `ColorMaskPlugin` в этом процессе.
- A3 классы: `message_module/adapters/message_adapter.py:43 MessageAdapter`, `message_module/core/message.py:48 Message`, `router_module/core/router_manager.py:130 RouterManager`, `router_module/channels/queue_channel.py:24 QueueChannel`; очереди — `shared_resources_module` (ROUTING_GLOSSARY.md:15, 57).
- A4 `config_module/__init__.py:16-25`: `__all__` = Config, ConfigManager, ConfigManagerConfig, ConfigSection, IConfigManager, IConfig.
- A5 `config_manager.py:29 class ConfigManager(BaseManager, ObservableMixin, IConfigManager)`; счёт `@abstractmethod`: IConfigManager 7 + IBaseManager 10 = 17 (скрипт по git show).
- A6 `git grep -n -E '^\s*(from|import) [A-Za-z_.]*router_module' 1dc6c71b7 -- '*.py'` без tests и самого router_module: process_module 14, frontend_module 3, multiprocess_prototype/frontend 3, process_manager_module 2, по одному — Plugins/_shared, Plugins/control, Services/modbus, Services/robot_comm (всего 30). Не из model.json.
- A7 `plugins/base.py:98 class PluginContext` (`self.config = config or {}` :115), `:1439 def config_class`, `generic_process_config.py:22 class PluginConfig(SchemaBase)`.
- A8 `threads/system_threads.py:39 "message_processor"`, `heartbeat/process_heartbeat.py:147 "heartbeat_sender"`, `generic/generic_process.py:308 "data_receiver"`, `:317 "pipeline_executor"`, `:358 f"source_producer_{source_plugin.name}"` (последние три — по условиям).
- A9 `multiprocess_prototype/backend/launch.py:403 def _resolve_pipeline(app, override)`: CLI-override > `app.pipeline`, голое имя -> `app.recipes / f"{override}.yaml"`.
- A10 ROUTING_GLOSSARY.md: имя процесса — аргумент `target` в `send_message(target, msg)`; канал Router — ключ реестра очередей (`control_*`), привязан к очереди `shared_resources_module`; «не обязаны совпадать» (`draw` -> `control_draw` против процесса `renderer`).

### Инъекции (прогноз назван до запуска; наблюдено)
| инъекция | прогноз красных | наблюдено |
|---|---|---|
| `need_all = False` в `classify` (убрать require all) | `test_require_all_needs_every_expected` | ровно он, 1 из 36 |
| цикл `for rel in qset["exclude"]` -> `for rel in []` (убрать вырезание ключа) | `test_clean_copy_excludes_answer_paths` | ровно он, 1 из 36 |
| `if tainted:` -> `if False:` (TAINTED выключен) | `test_violation_makes_verdict_tainted` | ровно он, 1 из 36 |
| (доп.) удалить строки `"require": "all",` из k0.json | `test_sets_load_and_expectations_are_well_formed` | НЕ красный: sed, видимо, ничего не удалил (ключ последний, без запятой) — вариант на данных не проверен |

Файлы после инъекций восстановлены из копий, `diff` — идентичны.

### What I interpreted rather than followed
- Поле `require` относится к адресам, для фактов отдельное `facts_require` (по умолчанию all); у `require` по умолчанию any.
- Полоса FIX: главная метрика на 1-2 ниже порога ИЛИ порог выполнен, но не выполнен другой (false, ratios); главная — `facts_hit` при заданном `facts_hit_min`, иначе `hits`.
- Хеш копии включает не только `exclude`, но и `context_files` (иначе карта прошлого условия видна следующему): имя `<sha>-<hash>`.
- Потолок адресов: учитываются первые `len(expected)+1`; при `sure` и неподошедшем ответе лишние = ложный адрес, при hit — игнорируются.
- `symbol` в k0 переведены в идентификаторы (verify-set ищет подстроку); `tolerance` Q2/Q3 = 0.
- A2 спрашивает про плагин `ColorMaskPlugin` (в топологии живут плагины, не модули framework); A9 — `_resolve_pipeline` (выбор топологии идёт через манифест/override).
- «Final context tokens» = input + cache_creation + cache_read последнего assistant-события (без output).

### What I left open / unreliable
- Ни одного живого запуска: `--tools` вместе с MCP, имена полей `usage` у assistant-событий, `--mcp-config` с шаблоном не проверены; возможен ложный TAINTED от служебных инструментов claude вне `--tools` (например ToolSearch).
- Команда сборки графа graphify (`/graphify . --update` в каталоге копии) и qex-индекса (`mcp__qex__index_codebase`) — по README плагинов, не запускалась; индекс qex ищется по `project_path` в `~/.qex/projects/*/project_info.json` (формат подсмотрен у одного проекта).
- Копия содержит `.claude/` и `CLAUDE.md` (не в exclude): хуки/память проекта могут влиять на сессию; `--setting-sources` не использован.
- A4 слабый: `ConfigManager` и `IConfig` — подстроки более длинных имён; A6 — счёт зависит от определения «единицы» и регэкспа; A8 — три имени воркеров условные.
- Факты — подстроки: правильный ответ другими словами не засчитается, неверный с нужными словами засчитается.
- Блайнд-тестера не было; на Windows `git archive` с симлинками пропускает элементы с предупреждением.
- Хук SubagentStop мог ругаться на `scripts/arch_map/build.py` — не мой файл.

memory hits: `search.py nav bench scoring agent benchmark` -> ничего релевантного (feedback_a_delta_benchmark_hides_what_sits_on_both_sides — про разностные бенчи цены, к этому бенчу не относится) | none relevant.

MEMORY LESSON | none
