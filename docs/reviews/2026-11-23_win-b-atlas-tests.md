# Win-B: тесты scripts/atlas на Windows (отчёт developer)

STATUS: DONE_WITH_CONCERNS (регрессия по остальным файлам каталога выполнена частично)

Патч: C:/Users/INNOTECH/AppData/Local/Temp/claude/65f734dde6ea3dc7/ad054591-efb3-40e2-a684-2e0d7b7b2962/scratchpad/patches/wf-b1.patch (git diff, 6 файлов, +41/-11). Не коммитил.

Импорт: `python -c "import multiprocess_framework as m; print(m.__file__)"` из корня worktree -> D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles--wf-b\multiprocess_framework\__init__.py

## Красные до правки (через гейт, по одному файлу)
- test_modules_roots_4_4: 1 failed, 12 passed
- test_modules_roots_blind: 1 failed, 46 passed
- test_file_not_parsed: 2 failed, 7 passed

## После правки (через гейт, по одному файлу)
- test_store_tree_blind_4_5d: 18 passed, 4 skipped
- test_store_tree_hazards: 10 passed, 4 skipped (2 новых + 2 прежних: time.tzset, geteuid/root)
- test_slow_gate_1_7a: 29 passed
- test_modules_roots_4_4: 13 passed
- test_modules_roots_blind: 47 passed
- test_file_not_parsed: 9 passed
- test_passport_map: 13 passed
- ruff check по шести файлам: без замечаний

## Регрессия по остальным файлам (по одному)
Прошли: adapters_code 13, adapters_commits 28, adapters_modules 9, adapters_plans 9, atlas_imports_guard 4, brief_1_9b 12, cache_1_6e 15, cache_1_6e_code 7 (все passed, 0 failed).
Остальные ~57 файлов не прогнаны: гейт ставит прогоны в очередь, один файл идёт минуты.

## Раунд 2 (F1): фикстура вместо skip
Маркер `_SKIP_NON_UTF8_ARGV` снят со всех шести тестов. Путь `bad\xff.py` теперь уходит в git через stdin
(`update-index --add -z --index-info`), а не в argv: падал `os.fsdecode` в фикстуре, не продукт.
Правка: `_commit_with_index_only_paths` (4_5d) и `_commit_bad_path` (hazards). Патч: scratchpad/patches/wf-b2.patch.
До: 4_5d 18 passed/4 skipped; hazards 10 passed/4 skipped. После: 4_5d 22 passed/0 skipped; hazards 12 passed/2 skipped
(оба прежние: time.tzset, geteuid). Регрессия: checkout_rename_retry 10, core_build 4, core_build_key 3, core_check 3 passed.

Инъекции (временные копии scripts/atlas в scratchpad, дерево не тронуто):
| инъекция | предсказано | наблюдено |
|---|---|---|
| A: Tree._ls без skip_undecodable | 4 a8 в 4_5d + test_non_utf8_path_skipped красные; git_z_is_strict зелёный | 4 failed/18 passed; 1 failed/11 passed/2 skipped (совпало) |
| B: git_z skip по умолчанию True | git_z_is_strict красный, остальное зелёное | hazards 1 failed (git_z_is_strict)/11 passed/2 skipped; 4_5d 22 passed (совпало) |
