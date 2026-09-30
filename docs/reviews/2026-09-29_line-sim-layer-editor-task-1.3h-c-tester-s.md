# Task 1.3h-c (S1–S4) — слепые RED-тесты `preset.sprites`

Роль: независимый tester, Sonnet 5.5. Worktree `ls-13hc-s-tester`, ветка `tests/ls-13hc-s-blind`, база `c8fe3540`.
Контракт — только раздел «Устройство бэкенда (c1)» и критерии S1–S4 плана `plans/line-sim-layer-editor/task-1.3h-c-layers.md`.
Читались (разрешено брифом): `Plugins/sim/layer_preview/plugin.py`, `tests/test_acceptance_1_3h_layout.py`,
`Plugins/sim/pult_web/tests/test_acceptance_1_3h_layout_route.py`, `_PRESET_ROUTES` / `_ERROR_CODE_TO_HTTP`,
`Services/line_sim/core/preview.py` (`confine_preset_paths`, `render_layout`), `LayerSpec`, `resolve_repo_path`.
Реализации `preset.sprites` в дереве нет; запрещённых путей не открывал (ls-layer, ls-13hc-c-tester, lp-flake, pult-flake).

## Файлы

1. `Plugins/sim/layer_preview/tests/test_acceptance_1_3h_c_sprites.py` — 18 тестов (S0–S3).
2. `Plugins/sim/pult_web/tests/test_acceptance_1_3h_c_route.py` — 5 тестов (S4).

Итого 23 теста при брифе «6–9»: разложено по свойствам (каждое ломается отдельно), а не по критериям. Лишнее
можно выкинуть без потери S1–S4; какие тесты «сверх минимума» — отмечено ниже.

## Прогон RED (команда брифа)

`PYTHONPATH=$PWD ../../../.venv/Scripts/python.exe -m pytest -q --tb=line <два файла>` → `22 failed, 1 passed`.
Единственный зелёный — контроль харнесса (`test_s1_control_...`), так и задумано.

Причина красного, одна на все 17 красных тестов sprites: `AssertionError: команда 'preset.sprites' отсутствует в
plugin.commands ({'preset.preview': ..., 'preset.layout': ...})` (16 — через `_call_raw`, 1 — прямой `test_s0`).
Причина красного всех 5 тестов route: `POST /api/preset/sprites -> 404 {'ok': False, 'error': 'not_found'}`
(в тесте «только layers» — пустой список вызовов клиента `layers`). Ни `ImportError`, ни падений фикстуры.

## Тесты и что каждый пинит

| Тест | Свойство | Красный сегодня потому что |
|---|---|---|
| s0_command_registered | `"preset.sprites" in LayerPreviewPlugin.commands` | нет ключа |
| s1_lists_recursive_case_insensitive_png_only | `a.png, sub/b.PNG, c.jpg, notes.txt` → ровно `["a.png","sub/b.PNG"]`, `sprite_source` `sprites/a.png` / `sprites/sub/b.PNG`, `truncated False` | нет команды |
| s1_order_is_full_path_sort_not_walk_order | `z.png, m/x.png, a.png` → `a.png, m/x.png, z.png` (обход «корень, потом подкаталоги» дал бы иное) | нет команды |
| s1_every_listed_sprite_source_loads_in_layout | оба `sprite_source` вписаны в слои → `preset.layout` ok, `size_px` слоёв = размеры именно этих файлов (24x12, 10x30) | нет команды |
| s1_control_source_relative_to_sprites_dir_is_rejected_by_layout | ЗЕЛЁНЫЙ контроль: `a.png` (от `sprites_dir`, не от каталога пресета) → `invalid` | — (проверяет, что загрузка выше не вакуумна) |
| s1_unicode_and_spaces_... | `папка 1/имя файла.png` → точный литерал записи, прямые слэши, грузится (16x9) | нет команды |
| s1_empty_dir_is_ok_with_empty_list_and_template | пустой каталог → `ok`, `files == []`, шаблон есть | нет команды |
| s1_dir_field_is_absolute_when_outside_repo | `dir` абсолютный, совпадает с `sprites_dir` | нет команды |
| s1_relative_sprites_dir_resolves_from_repo_root_not_cwd | cwd=tmp; `sprites_dir="Plugins/sim/layer_preview"` → ok, `dir == "Plugins/sim/layer_preview"` | нет команды |
| s2_template_keys_match_layerspec_fields_and_builds_layerspec | `set(template) == set(LayerSpec.model_fields)`, `LayerSpec(**{**tpl, name, sprite_source})` строится, JSON-сериализуем | нет команды |
| s2_template_defaults_are_literal | `mode=="static"`, `offset_px==[0,0]` и это list, `angle_deg==0`, `scale==1`, `augment/color_rgb is None`, `defect_probability==0` | нет команды |
| s3_missing_dir_is_io_error_with_path_in_message | нет каталога → `error/io_error`, в message `sprites_missing_zq7` | нет команды |
| s3_exactly_500_files_not_truncated | 500 → 500, `truncated False` (граница снизу) | нет команды |
| s3_501_files_cut_to_500_and_truncated | 501 → 500, `truncated True`, первый `f_000`, последний `f_499` | нет команды |
| s3_truncation_cuts_the_sorted_tail_not_the_walk_tail | 500 файлов `b_*` + `a/x.png`: в ответе `a/x.png` первым, `b_499` отрезан (см. «интерпретация» п.3) | нет команды |
| s3_symlink_to_file_outside_fence_is_omitted | симлинк на файл вне ограды отсутствует, `ok.png` есть; skip с причиной, если ОС не даёт симлинк (здесь симлинк создаётся — тест НЕ скипается) | нет команды |
| s3_dir_outside_fence_is_bad_request | хост с файлом пресета, каталог — брат каталога пресета → `bad_request` | нет команды |
| s3_dir_outside_repo_without_preset_file_is_bad_request | `preset_path=None`, каталог вне репо → `bad_request` | нет команды |
| s4_route_forwards_empty_body_to_layers_and_passes_reply_as_is | 200, тело как есть, `preset.sprites` ушёл ровно раз с `{}` | 404 |
| s4_route_targets_only_the_layers_client | ни robot/scene, ни другие клиенты не получили команду | пустой список вызовов |
| s4_route_timeout_is_like_layout | таймаут вызова 5.0 | вызова нет |
| s4_io_error_is_http_500_with_body_as_is | `io_error` → 500, тело как есть | 404 |
| s4_bad_request_is_http_400_with_body_as_is | (сверх S4) `bad_request` → 400 | 404 |

Сверх минимума S1–S4 (можно выкинуть первыми): `s1_unicode...`, `s1_empty_dir...`, `s1_dir_field_is_absolute...`,
`s1_relative_sprites_dir...`, `s3_exactly_500...`, `s3_dir_outside_repo_without_preset_file...`, `s4_bad_request...`,
`s4_route_timeout...`.

## Проверка выполнимости (не реализация, не в репо)

Чтобы убедиться, что красные тесты достижимо зелёные и не содержат собственных ошибок, я подключил через `-p`
черновую эталонную реализацию `preset.sprites` + строку в `_PRESET_ROUTES` (файл `sprites_ref.py` в scratchpad, вне
репозитория, не коммитится): `23 passed`. Это доказывает выполнимость набора и отсутствие ошибок в его собственной
оснастке; это НЕ доказывает, что он ловит поломки — инъекции лида впереди. Мутации против этого набора я не гонял.

Радиус (команда брифа, без нового файла sprites, т.к. он красный):
`Plugins/sim/layer_preview/tests Plugins/sim/pult_web/tests/test_acceptance_1_2h_preset.py` → `36 passed` (~11 с).

## What I interpreted rather than followed

1. **Таймаут «как у layout»** прочитан как `5.0` с (значение строки layout в `_PRESET_ROUTES`), пинится в `s4_route_timeout_is_like_layout`.
2. **`bad_request`/`io_error` — ответ команды, а не исключение `configure`.** Конфиг с `sprites_dir` вне ограды тест
   строит без ошибок и ждёт отказ в ответе `preset.sprites`. Если реализация проверяет ограду в `configure` и бросает —
   тесты `s3_dir_outside_*` упадут на ошибке конструирования; это решение лида, в плане не сказано.
3. **Усечение — ПОСЛЕ сортировки** (`s3_truncation_cuts_the_sorted_tail_not_the_walk_tail`). План: «порядок — по path; не больше 500,
   лишние отрезаются». Читаю как «сначала весь список по path, потом срез 500». Реализация, обрывающая обход на 500-м
   файле, тест завалит; если лид считает такое допустимым — тест удалить, остальное не зависит.
4. **`dir` внутри репо — относительно корня** (`Plugins/sim/layer_preview`), сравнение с нормализацией `\` → `/`.
   Тест на «в репо → относительный» есть; на «внутри репо и `\` в ответе» — терпим оба разделителя.
5. **Ключи ответа проверяются как подмножество** (обращаюсь к `status/dir/files/truncated/layer_template`), лишние ключи допустимы;
   у `files[i]` пинится доступ к `path`/`sprite_source` (у `s1_unicode` — полное равенство записи `{path, sprite_source}`, то есть
   там лишние ключи записи уже недопустимы: 1.3h-d будет отдавать ответ «той же формы»).
6. **«Путь в тексте» `io_error`** — проверяется только уникальный последний компонент `sprites_missing_zq7`, не полный путь
   (форма полного пути — `resolve()`, 8.3-имена и слэши на Windows делают подстроку хрупкой).

## What I left open / unreliable

- Не покрыто, потому что в плане нет ответа: `sprites_dir` указывает на ФАЙЛ (не каталог) — `io_error` или `bad_request`?;
  каталог, который сам называется `x.png`; несуществующий каталог ВНЕ ограды (`io_error` или `bad_request`); `preset.sprites` с
  не-dict телом (у соседних команд `bad_request`); симлинк-каталог наружу; симлинк ВНУТРИ ограды (в списке под именем ссылки
  или цели?); значение по умолчанию `data/line_sim` (каталога нет на свежем клоне — по контракту это `io_error`, но тест
  не привязан к `data/`, как и велел бриф).
- **`sprite_source` относительно `..`-цепочки не проверен**: хост с файлом пресета в tmp и каталог картинок в репо (ограда пускает
  оба) даёт путь через `..` и на Windows — через диск (`relpath` бросает `ValueError` между дисками). Контракт молчит, воспроизвести
  без каталога внутри репозитория нельзя (правило: tmp не в репо), а в дереве нет отслеживаемых PNG рядом с плагином.
  Так же не покрыт случай `preset_path=None` + каталог в репо (`sprite_source` от корня репозитория): нужен постоянный
  PNG в репо, брать его из `data/`/`apps/` я не стал.
- Симлинк-тест на этой машине РЕАЛЬНО выполняется (симлинки создаются). На CI без прав он скипается с причиной — это по брифу, но
  значит, что там свойство «симлинк наружу не в списке» непроверено.
- `s3_501...` / `s3_exactly_500...` создают по 500 файлов (~1–2 с каждый на NTFS); порог по времени не ставил.
- `pytest-timeout` не установлен: сами команды-по-карте синхронны и блокироваться не могут; HTTP-вызовы route-теста в daemon-потоке с дедлайном 15 с.
- Тесты не прошли break-injection (это стадия лида): ни одно свойство не подтверждено «убийством» под собственной поломкой.
  Слабое место, которое я предвижу: `s1_dir_field_is_absolute_when_outside_repo` слабо связан с контрактом («иначе абсолютный»
  не различает `str(resolved)` и `str(raw)`), так что мутация «отдать сырой `sprites_dir`» может выжить.
- Файлы тестов CRLF (как у соседей); `Plugins/sim/layer_preview/plugin.py` в этом коммите тоже CRLF (по `file`), а не LF, как сказано в брифе.
