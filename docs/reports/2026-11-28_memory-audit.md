# Аудит памяти уроков — предложение по уборке (этап 1 из 2, ничего не изменено)

Дата: 2026-11-28. Дерево: main checkout, `c9fbffa0c`. Каталог: `docs/claude/memory/`.
Метод: frontmatter всех 432 уроков и 185 архивных (скрипт поверх `scripts/memory/_lessons.py`),
кластеры по имени и `description`, полное чтение только кандидатов на слияние. Сырой список:
`C:/Users/INNOTECH/AppData/Local/Temp/claude/65f734dde6ea3dc7/96295c47-68c9-45a7-997e-358c9fc73c33/scratchpad/list1.txt`
(урок, байты, module, начало description; сгруппировано по первому mechanism).

Главный вариант по слову владельца («в архив, активными оставить только ключевые слова или содержание»;
«так же и с архивными»; «на темы, ключевые слова или ещё как-нибудь») — раздел 4.

---

## 1. Итоги и ожидаемый эффект

### Замеры сегодня

| Что | Сейчас |
|---|---|
| Активных уроков (`iter_lessons`) | 432 (338 feedback, 89 project, 5 reference), 1 488 034 байт |
| В `_archive/` | 185 (113 project, 71 feedback, 1 handoff), 806 935 байт |
| Ждут места (полоса Р2) | 8 |
| Тегов mechanism на урок | 1 тег — 78, 2 — 346, 3 — 8 (всего 794 вхождения) |
| `BY-MODULE-mechanism.md` | 79 513 байт при пределе 80 000 (`scripts/memory/by_module.py:16`) |
| Все `BY-MODULE*.md` | 196 145 байт (framework 47 145, other 36 439, tools 12 001, …) |
| `CRAFT-*.md` (ручные «содержания») | 40 157 байт, 123 строки-ловушки |
| `MEMORY.md` канон / кэш, грузится в каждую сессию | 9 585 / 10 331 байт при правиле 8 КБ |
| Средняя длина имени файла урока | 47 символов; строка mechanism-индекса ≈ 2×имя + 7 ≈ 100 байт |
| Архив: есть mechanism / module | 1 из 185 / 0 из 185 |
| Архив: description не двуязычен (проверка `desc-lang`) | 70 из 185 |
| Имена, которые есть И в активе, И в архиве | 4 (раздел 2.5): плоский перенос в `_archive/` их перезапишет |

### Эффект

| Величина | Сейчас | Только уборка (разделы 2.1–2.4) | Главный вариант (раздел 4) |
|---|---|---|---|
| Активных файлов-уроков | 432 | 410 (−22 слиянием) | ≈ 21 (решения владельца); прочие — в `_archive/` |
| Всего файлов-уроков (актив + архив + 8 новых) | 625 | 603 | ≈ 601 (−22 слиянием, −2 точных дубля архива — по желанию) |
| `BY-MODULE-mechanism.md` | 79 513 | ≈ 75 000 (−44 вхождения) — переполнится снова через ≈ 45 уроков | файла нет; его роль — страницы тем, каждая ≤ 25 КБ |
| Генерируемый индекс, всего | 196 145 (BY-MODULE) | ≈ 190 000 | ≈ 3 000 (`CONTENTS.md`) + ≈ 160 000 на 30 страниц (≈ 5,3 КБ в среднем) |
| Ручные содержания (CRAFT) | 40 157 | 40 157 | 0: их 123 строки становятся полем `trap:` уроков |
| `MEMORY.md`, грузится в каждую сессию | 9 585 (кэш 10 331) | ≈ 7 500 | ≈ 6 500 |
| Байт прочитать, чтобы найти урок | хаб 733 + слой до 47 145 или mechanism 79 513, или CRAFT 8–12 КБ | так же | `CONTENTS.md` ≈ 3 КБ + одна страница ≈ 6 КБ (наибольшая ≈ 25 КБ), или `search.py` без чтения индекса (вывод ≈ 1–2 КБ) |

Оценки главного варианта: строка содержания ≈ 290 байт (ловушка ≈ 110 кириллических символов ≈ 200 байт,
ссылка ≈ 70 байт) × ≈ 600 уроков. Замер на образце из раздела 4.4: 20 строк, блок 5 922 байт, строка в среднем 267 байт.

Вывод: уборка без смены схемы даёт ≈ 4,5 КБ и полтора месяца роста. Предел снимает только смена схемы индекса.
Длина текста урока на индекс не влияет.

---

## 2. Таблица действий (общая для обоих вариантов)

Метка «прочитан» значит, что я прочитал тело файла. Метка «по description» значит, что слияние выведено
из frontmatter: исполнитель этапа 2 читает тела перед слиянием, и если они расходятся, это не слияние.

### 2.1 MERGE

| # | Что сливать → во что | Причина | Проверка |
|---|---|---|---|
| M1 | `project_telemetry_gate_off_is_not_zero_ipc.md` → `feedback_gate_off_zeroes_deltas_not_messages.md` | тот же текст абзац в абзац, тот же замер 2026-08-14 | прочитаны оба |
| M2 | `feedback_commit_trailers_single_line.md` + `feedback_commit_validator_trailers.md` → `feedback_commit_trailer_no_wrap.md` | три урока об одном. Два первых устарели: `validate_commit.py:995` теперь сворачивает перенос («Git-style folding»). Ловушка «пустая строка перед Co-Authored-By» остаётся | прочитаны все три и код |
| M3 | `feedback_precommit_stash_collision.md` + `feedback_precommit_collision_recovery.md` → `feedback_precommit_stash_collision_2plus_agents.md` | один механизм `staged_files_only`: причина, повтор и восстановление | прочитаны начала всех трёх |
| M4 | `feedback_parallel_commit_sweep.md` + `feedback_concurrent_agent_writes_outside_git_index.md` → `feedback_commit_takes_the_whole_index.md` | один класс: чужое в индексе или в дереве уезжает в мой коммит | по description |
| M5 | `feedback_worktree_base_drift.md` → `feedback_worktree_stale_base.md` | тот же случай: `a50d1f74`, 76 коммитов позади, 2026-07-11 | прочитаны оба |
| M6 | `feedback_rename_injection_substring_trap.md` → `feedback_suffix_rename_is_a_blind_injection.md` | одна ловушка S-29: суффикс оставляет старое имя подстрокой | прочитаны оба |
| M7 | `feedback_windowed_voice_is_a_process_wide_singleton.md` + `feedback_windowed_voice_throttle_collides_with_sibling_tests.md` → `feedback_a_process_wide_throttle_turns_neighbours_vacuous.md` | один синглтон `process_voices()`, одна задача 2.12 | прочитаны все три |
| M8 | `project_emergency_log_is_stderr_only.md` → `feedback_emergency_log_reaches_stderr_not_the_log_files.md` | один факт: lastResort → только stderr | по description |
| M9 | `feedback_pytest_shows_captured_output_only_for_failures.md` → `feedback_red_tests_manufacture_the_appearance_of_new_diagnostics.md` | одно и то же свойство pytest | по description |
| M10 | `feedback_dual_write_by_copy_destroys_the_other_side.md` + `feedback_dual_write_memory_can_drift.md` → один файл | dual-write отменён (корневой `CLAUDE.md` «Память»: «ручного dual-write нет»); живая часть — только «кэш догоняет канон через diff» | по description; правило проверено в `CLAUDE.md` |
| M11 | `feedback_negative_wording_assertion_needs_an_existence_anchor.md` → `feedback_negative_criterion_needs_an_existence_anchor.md` | одно правило: отрицанию нужен якорь существования | по description |
| M12 | `feedback_null_stub_proves_red_on_literals_for_missing_cli.md` → `feedback_new_cli_flag_red_is_all_argparse_exit2.md` | RED для несуществующего CLI: заглушка доказывает ассерты | по description |
| M13 | `feedback_stand_lock_check_must_gate_the_command.md` → `feedback_shared_stand_and_tests_protocol.md` | оба про `stand.lock`. Теперь это механизм: `.claude/plugins/dev/hooks/machine-gate-guard.sh` блокирует голый pytest (строки 23, 46) | по description, хук прочитан |
| M14 | `feedback_a_sampling_watcher_misses_a_fast_overwrite.md` → `feedback_poller_misses_submillisecond_window.md` | опрос не видит окно короче своего такта | по description |
| M15 | `feedback_formal_review_before_merge.md` → `feedback_git_main_merge_hook_traps.md` | обе про ворота merge в main; ссылка на второй есть в `MEMORY.md` | по description |
| M16 | `feedback_qt_mcp_flag_value_is_compared_verbatim.md` → `reference_qt_mcp_launch.md` | одна ручка `QT_MCP_PROBE` | по description |
| M17 | `project_backend_ctl_full_flag_schema_gap.md` → `project_backend_ctl_mcp_surface_audit_2026_07_23.md` | дыра `full=true` — находка этого же аудита | по description |
| M18 | `feedback_explicit_model_per_agent_role.md` → `feedback_always_latest_models.md` | оба — правило владельца о выборе модели | по description |

Итого −22 файла. Перед каждым слиянием урок ищут через `search.py` по тем же словам.
У каждого результата слияния есть `merged_from:`.

### 2.2 ARCHIVE в старой схеме (правило уже стало механизмом или записано в загружаемом файле)

В главном варианте в архив уходят все уроки, так что этот список нужен только для `MEMORY.md`.
Строки этих уроков в `MEMORY.md` §1 дублируют правило, которое лид уже получает из загружаемого файла:

| Строка `MEMORY.md` / урок | Где правило уже есть |
|---|---|
| «commit берёт весь индекс» `feedback_commit_takes_the_whole_index.md` | `.claude/CLAUDE.md:12` «Stage explicit paths, never `git add -A`» |
| «uv sync сносит необъявленное» `feedback_uv_sync_prunes_venv.md` | `.claude/CLAUDE.md:13` «never `uv sync`» |
| «Merge в main» `feedback_git_main_merge_hook_traps.md` | корневой `CLAUDE.md` «Merge в main: тема `merge: <что вошло>` + Why/Layer/Refs» |
| «Субагенты в worktree … reviewer/tester синхронно» | `.claude/CLAUDE.md` «Subagents are background by default» (`run_in_background: false`) |
| «qex: сначала get_indexing_status» | корневой `CLAUDE.md` «MCP: qex» — строка сама это и говорит |
| `feedback_framework_tests_cannot_import_prototype.md` | `.sentrux/rules.toml` (boundaries framework→prototype) и корневой `CLAUDE.md` правило 9 |
| `feedback_sentrux_freetier_3rule_limit.md` | корневой `CLAUDE.md` «зелёный `check_rules` частичный» |
| `feedback_claude_cli_backend_costs_a_full_session.md` | корневой `CLAUDE.md` «`--backend=claude-cli` — сессия на батч» |
| `project_devseed_overwrites_claude_dir.md` | `.claude/CLAUDE.md` «claude-kit upgrade --apply preserves only …» |
| `feedback_three_lenses_three_defect_classes.md` | `.claude/CLAUDE.md` «Test authorship — three roles, three defect classes» |

Строки об апострофе, ruff и `PYTHONUTF8` дублируют `project-rules` §8, но лид `project-rules` не грузит
(`.claude/CLAUDE.md`: «the main session does not load project-rules»), поэтому эти строки в `MEMORY.md` остаются.

Устаревших уроков, у которых пропал код, почти не нашлось. Символы из 20 уроков проверены `git grep`
по `*.py`, и все живы: `TopologyEditorWidget` (2 файла), `FW_USE_KIND_CHANNELS` (6), `FW_STATE_TOPOLOGY_GATE` (4),
`windowed_voice` (47), `MetricsCollector` (8), `insert_many` (9), `PluginState.PAUSED` (11), `queue_data_loss` (2), …
Без такой улики ни один урок устаревшим не назван.

### 2.3 DELETE

В активном каталоге — ничего. Удалений с доказательством нет, а в главном варианте ничего не удаляется.

### 2.4 SHORTEN (тело > 9 КБ; на индекс не влияет, только на чтение)

| Файл | Байт | Что сжать |
|---|---|---|
| `feedback_qex_full_rebuild_runbook.md` | 20 278 | runbook: вынести в `docs/claude/TOOLING_NOTES.md` или в README плагина mcp-qex, в уроке оставить ловушки |
| `feedback_precommit_stash_collision_2plus_agents.md` | 18 321 (+M3) | после слияния — до ≈ 6 КБ: механизм, recovery `git show :path > path`, запрет слепого повтора |
| `feedback_injection_zero_may_mean_the_guards_were_not_collected.md` | 17 616 | повторяющиеся случаи свести к одной таблице |
| `project_telemetry_publisher_gate.md` | 15 451 | журнал PC 3.1–3.3 — это состояние трека, ему место в плане; оставить ловушки |
| `project_control_core_vision.md` | 13 069 | видение владельца — не трогать (раздел 3) |
| `feedback_plausible_is_not_verified.md`, `feedback_a_faithful_fake_still_lacks_the_protocol.md`, `feedback_framework_first.md`, `feedback_zero_observations_looks_like_a_result.md`, `feedback_sonnet_implements_opus_designs_and_reviews.md` | 10–12 КБ каждый | по возможности; `framework_first` — решение владельца, только с его согласия |

### 2.5 Коллизии имён актив/архив (решить до любого переноса)

| Файл | Состояние | Действие |
|---|---|---|
| `feedback_config_reload_ttl_addressing_guard.md` | тело в архиве совпадает побайтно (`diff` пуст); у активного `merged_from` на него | архивную копию удалить |
| `feedback_unkillable_fix_needs_a_hand_set_state.md` | то же: тело совпадает, `merged_from` есть | архивную копию удалить |
| `feedback_commit_trailers_single_line.md` | у активного `merged_from` на архивный; тексты различаются | уходит в M2; архивную копию переименовать с суффиксом `_v0` |
| `project_backend_ctl_missing_contract.md` | тексты различаются формулировками | сравнить вручную; более полный сохранить, другой переименовать с `_v0` |

### 2.6 RETAG

- 8 уроков полосы Р2: `services` → `services/device_hub`; механизмов `coordination`, `state`, `ipc` нет
  в `TAGS.yaml` (по их README). Ближайшие из словаря: `agents`/`git`, `config`, `ipc-routing`.
- В главном варианте — 184 архивных урока без mechanism и 185 без module, плюс 70 с одноязычным description.
  Иначе их не увидят ни `search.py --module/--mechanism`, ни генератор.
- Правило записи: первый тег mechanism — главный, он задаёт страницу темы; не больше двух тегов (раздел 4.6).

---

## 3. Что не трогать и почему

- **Решения владельца** (21 урок с `mechanism: owner-decision`; в том числе `feedback_framework_first.md`,
  `project_pipeline_recipe_driven_launch.md`, на которые ссылается корневой `CLAUDE.md` «Принципы владельца»,
  а также `project_control_core_vision.md`, `project_industrial_standards_packml.md`). Это действующие правила,
  а не уроки: их не сжимают и не сливают без владельца. В главном варианте они остаются в активном каталоге.
- **Строки `MEMORY.md` §1**, которые должны сработать раньше, чем о них вспомнят (раздел 4.3). В них сама
  строка и есть правило.
- **Тела уроков**: в главном варианте ничего не удаляется (слово владельца; `ARCHIVE.md`: «Правило не
  архивируется никогда» — в новой схеме правило остаётся строкой в `MEMORY.md` или на странице темы).
- **Ссылки на уроки в `docs/sessions/` (354 ссылки), `docs/handoffs/` (29), `docs/reviews/` (25)** — это история.
  Их не переписывают; искать файл по имени будет `search.py` (раздел 4.5).
- **Только локальные уроки** из кэша («Только эта машина» в локальном `MEMORY.md`) — их нет в git.
- **`TAGS.yaml`** правит только лид (шапка файла); новых механизмов этот аудит не вводит.
- **`.claude/agent-memory/*/MEMORY.md`** — у `tags.py` своё правило «не больше 3 строк».

---

## 4. Главный вариант: всё в архив, активным остаётся содержание

### 4.1 Как выбрать группировку — три способа

| Критерий | A. Страницы тем (по главному mechanism) + короткое `CONTENTS.md` | B. Указатель «ключевое слово → файлы» | C. Как сейчас: module + mechanism (BY-MODULE) |
|---|---|---|---|
| Байт прочитать, чтобы найти урок | ≈ 3 КБ `CONTENTS.md` + ≈ 6 КБ страница (наибольшая ≈ 25 КБ) | при 8 словах на урок ≈ 600 × 8 × 50 ≈ 240 КБ всего; по одной букве — 10–20 КБ | хаб 0,7 КБ + слой до 47 КБ, mechanism-список 79,5 КБ без описаний |
| Путь от симптома | симптом → класс ловушки («тест зелёный вхолостую» → `test-assertions`); строка называет саму ловушку | хорошо только при точном слове: русская морфология и синонимы рвут поиск | по модулю — если модуль известен; список mechanism без описаний ничего не говорит |
| Свежесть при новом уроке | генерируется из frontmatter (`trap:` + первый mechanism), руками не правится | генерируется, но это копия того, что `search.py` уже делает на лету без файла | генерируется |
| Может переполниться снова | страница — одна тема; при > 80 000 генератор делит её по слою (`config-framework.md`, …). Предела нет | да, растёт как уроки × слова | да: сегодня и случилось |

**Рекомендую A.** B не строить файлом: это и есть `search.py WORD…`, ему нужно только видеть `_archive/`
и поле `trap:`. Поиск по модулю тоже остаётся в `search.py --module`, отдельные файлы не нужны.

### 4.2 Что активно, а что в `_archive/`

```
docs/claude/memory/
  MEMORY.md            ≤ 8 КБ, ручной, грузится в каждую сессию (4.3)
  CONTENTS.md          генерируется: 30 строк «тема — открывать, когда … — N уроков» (≈ 3 КБ)
  contents/<mech>.md   генерируется: одна страница на механизм из TAGS.yaml, внутри — по слою и модулю
  TAGS.yaml            словарь (как сейчас)
  ARCHIVE.md           история закрытых треков, как сейчас (читают целенаправленно)
  <решения владельца>  ≈ 21 файл, остаются на месте
  _archive/*.md        тела всех остальных уроков: 411 активных + 8 Р2 + 185 архивных
```

- Каждый урок стоит на одной странице — странице своего первого mechanism. Второй тег пишется в строке
  как `+guards`. Тогда строк ≈ 600, а не 794 + 185.
- **Строка называет ловушку, а не тему.** Для этого во frontmatter вводится поле `trap:`: одна русская строка
  до ≈ 120 символов вида «X выглядит как Y, а на деле Z». `description` остаётся двуязычным ключом поиска.
  Начальные значения: 123 строки CRAFT (они уже написаны как ловушки), остальное — из `description`
  руками агента (4.7).
- `BY-MODULE*.md` (196 КБ) и `CRAFT-*.md` (40 КБ) уходят. CRAFT — в `_archive/`, потому что на них есть ссылки.

### 4.3 Что остаётся полностью на виду (`MEMORY.md`, ≈ 6,5 КБ)

Строки, которые должны сработать до того, как о них подумают, — только в `MEMORY.md`, и каждая
самодостаточна (правило целиком, ссылка на тело — по желанию):

- проверка: ноль наблюдений и «0 красных» (collected числом), правдоподобное ≠ проверенное, утверждение
  об отсутствии + достижимость, сторож «хоть раз» слеп, дублёр верен форме, число без разброса,
  посылка и причина из плана — гипотезы;
- общее дерево: чужая сессия в том же дереве, pre-commit и 2 агента (recovery `git show :path > path`);
- окружение лида (его нет в загружаемых `CLAUDE.md`): апостроф в Bash, ruff и свежий импорт,
  `PYTHONUTF8`/cp866, глобальный taskkill, CR в `read < <(...)`, `rg`/qex слепы к `docs/`,
  autouse-изоляция HOME, venv держит MCP, чёрный кадр = пакет 8164;
- решения владельца — 13 строк, как сейчас;
- одна строка-указатель: «урок по симптому — `CONTENTS.md` или `search.py <слова>`».

Убрать из `MEMORY.md`: строки, повторяющие загружаемые `CLAUDE.md` (таблица 2.2, ≈ 1 КБ); раздел
«Указатели» — 7 строк свернуть в 1; раздел 3 «Окружение» оставить только из ловушек (≈ 1,3 КБ уходит
на страницу `windows-env`). Ещё исправить мёртвую ссылку: `MEMORY.md` строка 4 указывает на `_archive/INDEX.md`,
а такого файла нет (`ls` → No such file); настоящий файл — `ARCHIVE.md`.

Остаются ли уроки полностью активными? Только решения владельца (≈ 21 файл). Тела уроков §1 уходят
в архив, их правило остаётся строкой. Причина: в каждую сессию грузится только `MEMORY.md`,
активный каталог в контекст и так не попадает, так что держать там тела незачем.

### 4.4 Образец: 20 строк содержания (модуль `process_module`, как они лягут по страницам)

Ниже — 20 из 43 уроков с `module: process_module`. Ловушки я написал по их description;
файлы, отмеченные в 2.1, прочитаны целиком. Замер: блок 5 922 байт, строка в среднем 267 байт.

```markdown
<!-- contents/config.md — сгенерировано search.py --contents --write; не править -->
# config — конфигурация: дефолты, слои, фасады, схемы, env (… уроков)
## framework / process_module
- Поле есть в схеме менеджера, а ручка не управляется: фасад — белый список и молча выбрасывает чужой ключ · [→](../_archive/feedback_facade_is_a_whitelist_not_a_passthrough.md)
- Ключ рецепта не доезжает до процесса, если его нет в `ProcessConfig._from_recipe`/extras; metadata читает только легаси · `+recipe` [→](../_archive/feedback_recipe_knob_must_be_named_in_from_recipe.md)
- Новая под-секция без своего менеджера идёт мимо сверщика: ручка действует, вердикт её не судит · `+guards` [→](../_archive/feedback_a_knob_can_be_applied_and_unverifiable.md)
- Ноль законен у источника и вырожден у потребителя — страж у источника отменяет решение оператора · `+guards` [→](../_archive/feedback_a_degenerate_value_is_not_zero_it_is_unknown.md)
- `extra=ignore` молча съедает ещё не объявленный kwarg — RED «новое поле» должен читать атрибут, а не ждать ошибки · `+test-assertions` [→](../_archive/feedback_pydantic_extra_ignore_hides_red.md)
- Встроенный путь `config.reload` отвергает неизвестные ключи observability, сырой SchemaBase — нет: две двери, два поведения · `+test-assertions` [→](../_archive/feedback_config_reload_inline_rejects_unknown_observability_keys.md)
- Новый тумблер observability — 4 точки касания; пропуск одной даёт ручку, которой нет в `expand_observability` · `+architecture` [→](../_archive/project_observability_facade_extension.md)
- Publisher-гейт телеметрии жив только при секции `telemetry.publish`; пустую не инжектить — гейт тогда выключен · `+concurrency` [→](../_archive/project_telemetry_publisher_gate.md)

<!-- contents/guards.md -->
## framework / process_module
- Слой, который приводит тип (coercion), снимает более строгий страж, стоявший за ним · `+config` [→](../_archive/feedback_a_new_guard_can_weaken_an_old_one.md)
- Edit, где old_string захватил соседний метод, а new_string его не повторил, молча удаляет соседа · `+test-assertions` [→](../_archive/feedback_an_edit_that_replaces_a_neighbour_drops_it.md)

<!-- contents/break-injection.md -->
## framework / process_module
- Тридцать сторожей зовут хелпер напрямую и зелены при снятом единственном боевом вызове — инъектировать call site · [→](../_archive/feedback_inject_the_call_site_not_only_the_helper.md)
- «Константа вместо прочитанного» зелёная, если на всех фикстурах константа равна факту — нужна третья точка · `+fixtures` [→](../_archive/feedback_injection_green_when_the_substitute_equals_the_fact.md)

<!-- contents/lifecycle.md -->
## framework / process_module
- `PluginState.PAUSED` — ярлык, не гейт: `call_process` смотрит только `enabled`, плагин на паузе получает `process()` · [→](../_archive/project_plugin_paused_is_a_label.md)
- spawn копирует sys.path родителя: PYTHONPATH внутри pytest до детей не доходит, инъекция в дочернем коде молчит · `+break-injection` [→](../_archive/feedback_spawn_child_inherits_parent_sys_path.md)
- Последняя запись сегмента lifetime в фазе 2 идёт первой (LIFO) без срока — блокирующий вызов съедает бюджет сегмента · `+concurrency` [→](../_archive/feedback_blocking_first_lifo_entry_steals_segment_budget.md)
- «Готов» значило «инициализирован», читали как «принимает команды» — команда в это окно терялась молча · `+ipc-routing` [→](../_archive/feedback_ready_signal_meant_less_than_read.md)
- `_do_shutdown()` на плагине в IDLE не падает и не убирает ничего — тест teardown зелен вхолостую · `+test-assertions` [→](../_archive/feedback_do_shutdown_on_unbooted_plugin_is_a_silent_noop.md)

<!-- contents/measurement.md -->
## framework / process_module
- Закрытый гейт обнуляет дельты `state.changed`, но не число IPC-сообщений — считать дельты, иначе рабочая фича «не сработала» · `+acceptance` [→](../_archive/feedback_gate_off_zeroes_deltas_not_messages.md)
- Кумулятивный max в периодической строке лога прячет максимумы устойчивого режима ниже стартового · `+performance` [→](../_archive/feedback_cumulative_max_hides_steady_state.md)

<!-- contents/ipc-routing.md -->
## framework / process_module
- Идемпотентность спасает от дубля, но не от «стейл после свежего»: второму пути доставки нужен порядок · `+concurrency` [→](../_archive/feedback_idempotent_is_not_monotonic.md)
```

### 4.5 Что перестанет работать, когда урок в `_archive/`, и что поменять

Проверено чтением `scripts/memory/`, `scripts/validate.py`, `.claude/commands/core/memory/*.md`,
`project-rules` §8 и хуков из `.claude/settings.json`:

| Что | Сейчас с `_archive/` | Что поменять |
|---|---|---|
| `_lessons.iter_lessons` (`_lessons.py:118`) | берёт только `*.md` прямо в каталоге, `_archive/` не видит | параметр `include_archive=True` (или `_archive/*.md` по умолчанию) |
| `search.py` — подсказка субагентам (`project-rules` §8) | 185 архивных уроков **уже сейчас не находятся** | искать в обоих каталогах; искать и по `trap:`; режим `--path <stem>`, чтобы находить файл по старой ссылке |
| `by_module.py` + `validate.py` проверка 9 | генерирует BY-MODULE из активных | заменить генератором страниц тем; предел 80 000 на страницу оставить, при переполнении делить по слою; `scripts/memory/tests/test_by_module_blind.py` переписать |
| `tags.py --check` + `validate.py` проверка 8 | архив не проверяется | проверять архив тоже: тогда сразу 185 `no-tag` и 70 `desc-lang`, так что разметка (4.7) идёт до включения; плюс новая ошибка `no-trap` |
| `[[name]]`-ссылки (1 321 штука) | ищутся по имени, их не разрешает ни один скрипт или хук (поиск по `scripts/` и хукам их не нашёл) | переживают перенос как есть |
| Относительные ссылки `](name.md)` внутри памяти | 219 ссылок на активные уроки (CRAFT, MEMORY, уроки) сломаются | `MEMORY.md` переписать на `_archive/…`; `scripts/claude_md_audit` (`memory_links = true`) проверяет ссылки `MEMORY.md` и поймает пропуск |
| Ссылки снаружи | 498 ссылок на 258 уроков: 354 из `docs/sessions/`, 29 handoffs, 25 reviews, 6 из корневого `CLAUDE.md`, остальное — планы | живые (`CLAUDE.md`, `.claude/`, активные планы) переписать; историю не трогать, её закрывает `search.py --path` |
| `/core:memory:remember` | шаг 3 пишет урок в корень каталога; **шаг 4 велит добавлять каждый урок строкой в `MEMORY.md`** — это источник переполнения 8 КБ; шаг 3 ссылается на `memory_lint.py`, а такого файла нет (`ls scripts/memory_lint.py` → нет) | писать в `_archive/` с `trap:`; строка в `MEMORY.md` — только для правила «срабатывает до поиска»; шаг 5 — новый генератор |
| `/core:memory:search` | `grep -r` рекурсивен — `_archive/` уже видит | без изменений |
| `project-rules` §8 (`merged_from`) | путь не указан | указать `_archive/` (правка в `.claude/plugins/…`, затем копия байт в байт в `.claude/skills/`) |
| Локальный кэш автопамяти (277 файлов) | ссылки `MEMORY.md` разрешаются в кэше | в кэш тоже завести `_archive/`; обновлять через `diff`, как велит `CLAUDE.md` |
| `session-memory-banner.sh` | считает записи в `.claude/memory` | не затронут |

### 4.6 Чтобы индекс не заполнился снова

| Вариант | Плюс | Минус |
|---|---|---|
| a. Разбить `BY-MODULE-mechanism.md` на части | одна строка кода, ничего не теряется | всего по-прежнему ≈ 80 КБ имён без описаний; растёт дальше |
| b. В индекс mechanism — только первый тег | 794 → 432 вхождения, 43 381 байт (замерено генератором); правка в одну строку (`for m in mechanisms[:1]`) | вторые теги видны только через `search.py --mechanism`; предел вернётся примерно на 800 уроках |
| c. Поднять предел | ноль работы | откладывает, CTO уже выносил вердикт о пределе (`2.4j.md:11`) |
| **d. Страницы тем A (4.1)** | страница = тема, переполнение лечится делением по слою; строка называет ловушку; CRAFT больше не ведётся руками | этап 2: новый генератор с тестами, поле `trap:` у ≈ 600 уроков |

**Рекомендую d**, а до этапа 2 — b как разблокировку сегодня: одна строка в `by_module.py`,
и 8 уроков Р2 можно положить на место. Правила при записи урока (в `remember.md` и `project-rules` §8):
`trap:` обязателен; mechanism — 1–2 тега, первый главный; строка в `MEMORY.md` — только для
правила «до поиска»; сначала `search.py`, при совпадении — обновить файл с `merged_from`.

### 4.7 Отдельно: что из архива можно безопасно удалить (не входит в главный вариант)

Только 2 файла с доказательством: `_archive/feedback_config_reload_ttl_addressing_guard.md` и
`_archive/feedback_unkillable_fix_needs_a_hand_set_state.md`. Тело каждого совпадает с активным побайтно
(`diff` тел пуст), а у активного стоит `merged_from` на архивный. Остальные 183 архивных файла я
на дубли не проверял, поэтому удалять из них ничего не предлагаю.

---

## 5. Что не проверено, и объём этапа 2

Не проверено:
- Тела M4, M8–M18 (слияние выведено из description). Тела 2.4 SHORTEN целиком. 183 архивных файла на дубли и устаревание.
- Устаревание проверено только по 20 символам кода, без поиска «а исправлено ли» по истории треков.
- Сколько уроков ляжет на каждую страницу темы: у архивных главного mechanism ещё нет, поэтому
  «наибольшая ≈ 25 КБ» — оценка, а не замер.
- Корневой `CLAUDE.md` пишет «трейлер — одной строкой, иначе hook отклонит коммит», а
  `validate_commit.py:995` сворачивает перенос. Похоже, правило устарело наполовину; тестом
  я это не проверял. Вопрос для `docs/claude/OPEN_QUESTIONS.md`.
- Ловушка «пустая строка перед Co-Authored-By» при новом парсере не воспроизведена.

Объём этапа 2 (главный вариант):
1. **Задача A, инструменты** (Middle+, developer; стадии 0/1/3/5 по `.claude/CLAUDE.md`): `_lessons.py`,
   `search.py`, генератор страниц вместо `by_module.py`, `tags.py` (`no-trap`, проверка архива),
   `validate.py`, тесты `scripts/memory/tests/`, `remember.md`, `project-rules` §8 + зеркало.
   ≈ 8 файлов, ≈ 250–350 строк.
2. **Задача B, данные** (sonnet-агенты пачками по ≈ 30; Haiku на разметке памяти давал 72 % совпадения —
   `project_haiku_classifier_failed_memory_tagging.md`): 22 слияния, 4 коллизии, module/mechanism
   для 185 архивных, 70 description, `trap:` для ≈ 600 уроков (123 — из CRAFT), `git mv` ≈ 420 файлов,
   переписать живые ссылки, новый `MEMORY.md`, генерация.
3. Оценка: 2 сессии, ≈ 1–1,5 млн токенов агентов (разметка ≈ 250 тыс., `trap:` ≈ 200 тыс.,
   слияния ≈ 150 тыс., задача A с тестером и ревьюером ≈ 600 тыс.).
4. Разблокировка сегодня (вариант b) — одна строка и перегенерация. Это solo-тривиально, но правит
   механизм с тестами: нужен прогон `scripts/memory/tests` и ревью.
