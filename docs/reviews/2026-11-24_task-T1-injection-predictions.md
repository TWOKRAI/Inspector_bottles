# T1 (LatestMailbox): предсказания инъекций лида, записаны ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t1-dev` (ветка feat/gfp-t1-latest-mailbox, база bc82d9363). Модуль: `multiprocess_framework/modules/process_module/generic/latest_mailbox.py`. Два набора тестов: [T] = `tests/test_latest_mailbox.py` (слепой tester, 27 тестов), [H] = `tests/test_latest_mailbox_hazards.py` (автор, 9 тестов). Каждая мутация прогоняется против ОБОИХ наборов (правило проекта). Базовая линия: [T] 27 passed, [H] 9 passed.

Исполнитель мутаций — developer T1 (он владелец файла): мутация в копии/временной правке с откатом по sha256 из байтовой копии. «Красный набор (минимум)» — тесты, которые ОБЯЗАНЫ упасть; дополнительные красные не из набора фиксируются отдельно и не считаются расхождением, если мутация шире (помечено «шире»); тест из набора, оставшийся зелёным, — находка.

| № | мутация | красный набор (минимум) | примечание |
|---|---|---|---|
| M1 | общий FIFO/один слот вместо словаря по ключам (put кладёт в общую структуру, take(key) ищет по ключу) | [T] test_keys_are_independent_fast_key_does_not_evict_slow_key; test_second_put_same_key_supersedes_first; test_bytes_held_never_exceeds_latest_per_key | шире: pending_keys и stats-тесты; [H] — не обязательно красный |
| M2 | take не удаляет запись (возвращает, но ключ и байты остаются) | [T] test_take_removes_item_second_take_returns_none; test_max_keys_rejects_and_counts; test_max_keys_counts_waiting_keys_not_keys_ever_seen; test_pending_keys_lists_keys_with_waiting_item | шире: invariant-тесты |
| M3 | замена не вычитает байты старого элемента | [T] test_second_put_same_key_supersedes_first (bytes_held 40); test_bytes_held_never_exceeds_latest_per_key; test_max_bytes_held_is_peak_after_replacement | [H] bytes_held == 10 * pending красный |
| M4 | max_bytes_held обновляется до вычитания старых байт | [T] test_bytes_held_never_exceeds_latest_per_key (23328000 вместо 18662400); test_max_bytes_held_is_peak_after_replacement (270 вместо 170); test_invariant_holds_across_mixed_sequence (max 60 вместо 50) | |
| M5 | отвергнутый put попадает в счётчик put | [T] test_max_keys_rejects_and_counts; test_invariant_holds_across_mixed_sequence | |
| M6 | возраст считается от первого put (при замене метка времени не обновляется) | [T] test_take_returns_age_from_injected_clock | |
| M7 | clear обнуляет max_bytes_held | [T] test_clear_counts_superseded; test_invariant_holds_across_mixed_sequence | |
| M8 | clear не считает выброшенное в superseded | [T] test_clear_counts_superseded; test_invariant_holds_across_mixed_sequence | [H] test_clear_races_with_put_and_take — вероятно красный (инвариант) |
| M9 | max_keys считает ключи за всё время, а не ожидающие | [T] test_max_keys_counts_waiting_keys_not_keys_ever_seen; test_max_keys_rejects_and_counts (слот свободен после take) | |
| M10 | замок снят целиком (threading.Lock -> contextlib.nullcontext) | [H] ВСЕ 9 при setswitchinterval(1e-6) (developer сам получил 9 красных из 9); [T] 27 зелёных | без setswitchinterval [H] зелёные (0 красных): это ожидаемо |
| M11 | замок снят только в stats() (put и take под замком) | [H] test_invariant_holds_under_two_threads — лид НЕ уверен (читатель берёт снимки stats); результат фиксировать как наблюдение | [T] 27 зелёных |
| M12 | pending_keys отдаёт ключи в алфавитном порядке | [T] test_pending_keys_lists_keys_with_waiting_item (k3,k1,k2); test_keys_are_independent_fast_key_does_not_evict_slow_key (["slow","fast"]); test_pending_keys_replacement_keeps_position (b,a,c); test_pending_keys_key_after_take_and_new_put_goes_last (y,z,x) | test_key_is_opaque_string, вероятно, зелёный (ключи уже в алфавитном порядке) |
| M13 | замена существующего ключа переставляет его в конец порядка pending_keys | [T] test_pending_keys_replacement_keeps_position | |
| M14 | age_s возвращается как clock() (без вычитания времени put) | [T] test_take_returns_age_from_injected_clock; test_age_is_per_key | |
| M15 | clear не освобождает слоты max_keys (счётчик ключей не уменьшается) | [T] test_clear_frees_max_keys_slots | |
| M16 | замена существующего ключа при заполненном max_keys отвергается | [T] test_max_keys_rejects_and_counts (put при полном пределе должен дать True) | |

Критерий находки: (a) тест из «красного набора (минимум)» остался зелёным; (b) мутация после отката дала иную sha256 файла; (c) красный набор [T] при мутации M10 НЕ пуст (в первой редакции критерия было написано «не пуст» по ошибке; правильно — [T] обязан остаться зелёным, 27 passed: замок не виден однопоточным тестам; исправлено лидом после прогона, результат матрицы это подтвердил).
Файлы прогона после каждой мутации (по одному, через `bash scripts/machine_gate.sh light inspector-bottles-K ../../../.venv/Scripts/python.exe -m pytest -q --tb=line -p no:cacheprovider <файл>`): tests/test_latest_mailbox.py; tests/test_latest_mailbox_hazards.py.
