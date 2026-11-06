# map-A1 — прогнозы инъекций (лид, записаны ДО прогона)

Дата 2026-11-06. Записано, пока разработчик пишет GREEN (коммит тестера `e6a46261a`, кода ещё нет). Каждая инъекция
ломает ОДНО свойство; ожидаемый набор красных — по именам. Красные тестера — `scripts/atlas/tests/test_scan.py`
(далее `T::`), тесты автора — `scripts/atlas/tests/test_scan_hazards.py` (далее `H::`). База матрицы — прогон обоих
файлов без `-k`, число collected — в отчёт (урок «ноль красных = не собрались сторожа»).

| # | Инъекция (одна правка) | Ожидаемые красные | Комментарий |
|---|---|---|---|
| I1 | `scan`: кэш никогда не читается (всегда промах) | `T::test_blob_cache_reparses_only_changed_oids`, `T::test_one_git_process_per_scan`, `T::test_scanner_change_is_full_miss`, `T::test_unparsable_source_gives_error_facts` (D1: повторный `hits == 1`), `T::test_facts_depend_only_on_content` (если считает `hits`) | ядро кэша |
| I2 | ключ кэша без `scanner` (только `oid`) | `T::test_scanner_change_is_full_miss` | |
| I3 | `all`/`doc`/`tier`/`contour` считаются только у `__init__.py` (как в карте) | `T::test_facts_depend_only_on_content`; `T::test_all_plus_equals` и `T::test_header_tier_contour_parsed`, если их вход — не `__init__.py` | R5 |
| I4 | не снимать `﻿` перед `ast.parse` | `T::test_unparsable_source_gives_error_facts` | R4 |
| I5 | `scan_text` ловит только `SyntaxError, ValueError, UnicodeDecodeError` (без `RecursionError`) | `T::test_unparsable_source_gives_error_facts`, `H::test_pathological_sources_isolated_from_neighbours` | исключение вылетает |
| I6 | импорт в `def` внутри тела `if TYPE_CHECKING` -> `lazy` (поведение карты) | `T::test_import_kinds_hard_lazy_tc` | отступление R9 |
| I7 | `guarded = True` для любого `try`, независимо от обработчика | `T::test_guarded_relative_import_marked_guarded` | |
| I8 | `methods` отбрасывает все имена с `_` (поведение карты) | `T::test_class_methods_keep_dunder_members` | D5 |
| I9 | `oids()` включает символьные ссылки и gitlink | `T::test_one_git_process_per_scan` (пункт files/oids) | |
| I10 | `oids()` запускает свой `ls-tree`, не общий с `files()` | `T::test_one_git_process_per_scan` | |
| I11 | убрать проверку перевода строки в пути в `read_blobs` | `T::test_one_git_process_per_scan` (пункт `read_many`), `H::test_paths_with_space_cyrillic_newline_do_not_shift_batch` | правка 2 раунда 2 |
| I12 | `from pkg import n`: цель всегда файл `pkg`, подмодуль не ищется | `T::test_from_pkg_import_submodule_targets_submodule` | R7 |
| I13 | `resolve_relative`: у `__init__.py` уровень 1 поднимается на пакет выше | `T::test_init_level_one_is_package` | |
| I14 | `MAX_BLOB_BYTES`: `>=` вместо `>` | `T::test_unparsable_source_gives_error_facts` (граница 1_048_576 -> `error is None`) | D1 |
| I15 | oid `DictSource` = `sha1(data)` без заголовка `blob N\0` | `T::test_tree_and_dict_source_give_equal_facts` | |
| I16 | `commands` не сортируются | `T::test_commands_and_threads_literals` | |
| I17 | `__all__ += [...]` не учитывается | `T::test_all_plus_equals` | |
| I18 | `Tier:` без приведения к нижнему регистру | `T::test_header_tier_contour_parsed` | R8 |
| I19 | `get_scans` без порций по 500 (один `IN (...)`) | **ожидаю 0 красных** | sqlite ≥ 3.32 держит 32766 параметров; `H::test_get_scans_chunks_over_500_oids` поймает, только если наблюдает порции, а не результат. Если зелёный — вакуум, находка к тесту автора |
| I20 | `put_scans`: коммит на каждую строку вместо одной транзакции | **ожидаю 0 красных** | свойство — время (fsync на Windows), сьютом не проверяется; меряет скрипт лида |
| I21 | `get_scans` пропускает `OperationalError` наверх | `H::test_db_locked_by_writer_scan_still_returns_facts` | правка 1 раунда 2 |
| I22 | битое тело в кэше -> исключение вместо промаха | `H::test_broken_cache_body_is_miss_and_rewritten` | |

Ожидаемое число: 20 инъекций с красными, 2 с нулём (I19, I20 — известные дыры без сторожа, не дефект кода).
Несовпадение набора — находка: лишний красный = тест хрупкий; недостающий = вакуумный тест.
