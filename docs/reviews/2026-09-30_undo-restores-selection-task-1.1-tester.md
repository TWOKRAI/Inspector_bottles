# Task 1.1 — слепые приёмочные тесты (tester, RED)

Ветка `tests/undo-sel-blind`, worktree на коммите плана fd7ec54e. Реализации нет. Режим: RED (заголовок MODE в брифе
отсутствовал, бриф свободный — трактован как RED). Формальный `interface.py` отсутствует: тестировал против API,
зафиксированного в плане, и таблицы контракта («spec text only»).

## Запуск

`PYTHONPATH=$PWD ../../../.venv/Scripts/python.exe -m pytest <оба файла> -q --tb=line -p no:cacheprovider`
Итог: `20 failed, 9 passed`. Соседние `test_presenter_domain_dispatch.py` + `test_place_display.py`: `55 passed`
(импорты хелперов их не ломают).

## Framework — `actions_module/tests/test_acceptance_snapshot_memo.py` (18 тестов: 13 RED, 5 GREEN)

RED — `TypeError: record() got an unexpected keyword argument 'memo_before'` или
`AttributeError: 'SnapshotHistory' object has no attribute 'take_undo_with_memo'` (не ImportError; тип TypeError,
а не NotImplementedError/AttributeError из шаблона — потому что новый kwarg у существующей функции):
- test_record_accepts_memo_and_undo_returns_memo_before, test_redo_returns_memo_after,
  test_memo_survives_repeated_undo_redo_cycles, test_with_memo_on_empty_stacks_returns_none,
  test_plain_take_undo_still_returns_only_snapshot_for_memo_entry,
  test_memo_stays_with_entry_when_mixing_plain_and_with_memo_calls, test_entry_without_memo_yields_none_memo
- A7: test_a7_coalescing_keeps_first_before_and_newest_after, test_a7_different_coalesce_keys_do_not_merge_memos
- A8: test_a8_truncation_and_clear_release_memos[truncation|clear],
  test_a8_clear_releases_memos_of_redo_stack_too, test_a8_new_record_releases_memos_of_redo_stack

GREEN (пиннят поведение, которое обязано пережить реализацию, A9): без-memo последовательность undo/redo,
идентичность снимков (`is`), coalescing без memo, обрезка max_history без memo, новая запись чистит redo.

## Qt — `pipeline/tests/test_acceptance_undo_selection.py` (11 тестов: 7 RED, 4 GREEN)

RED (все — `AssertionError` неверного выбора после undo/redo, не ошибка сетапа):
A1, A3, A3 (мульти-выбор), A4, A5b, A7 (undo), A7 (redo).
GREEN: A2, A5, A6 (x2) — выбор и так сохраняют выжившие узлы (G.6.3).

## Как гонял вкладку

Реальный `PipelinePresenter` + `GraphScene` + `CommandDispatcherOrchestrator` через `_make_orchestrator_services` и
`_build_presenter_with_scene` (импорт, не копия). add = `presenter.add_process_from_plugin("blur")`,
delete = `presenter.remove_selected([...])`, правка = `presenter._on_inspector_field_changed("camera", field, value)`
(dispatch SetPluginConfig с `coalesce_key`), undo/redo = `services.commands.undo()/redo()`. A6 = прямой
`services.commands.dispatch(AddProcess(...))`.

## Что я истолковал, а не выполнил буквально

1. **Id узлов — `<процесс>.<плагин>`** (`camera.capture`, `processor.color_mask`, `blur.blur`, `extra.blur`), а не
   имена процессов, как в брифе («литеральные id из таблицы плана» — в плане id нет). Выяснено запуском сцены.
   `remove_selected` принимает эти же id узлов. Правка поля берёт имя ПРОЦЕССА (`"camera"`).
2. **A1, A2, A3 (голые), A4 в буквальной формулировке зелёные уже сегодня** (G.6.3 оставляет выживших). Чтобы они
   проверяли память записи, между операцией и Отменой добавлен клик пользователя (по новому узлу / по другому узлу /
   по пустому месту). Без клика A1 не был бы красным, вопреки прогнозу в брифе. A2 и A5 остались зелёными даже с кликом.
3. **A4** взят с двумя выбранными узлами (camera+processor, удаляется camera), иначе выбор «сразу после удаления»
   пуст и тест не отличает «after» от «ничего».
4. **A5b (лишний, мой)**: выбран B → правка → клик по другому → Отмена → B. Это обобщение таблицы («выбор — часть
   записи»); в таблице этого ряда нет. Если лид считает иначе — удалить.
5. Лишние framework-тесты сверх списка: memo при смешанных вызовах take_undo/take_redo_with_memo, redo-стек и
   `clear()`/новая запись отпускают memo, A7 с разными ключами. Всё выведено из фразы «memo хранятся только внутри записей».
6. A7 дополнен проверкой «второй undo -> False» (серия одним шагом) и redo-веткой (выбор ПОСЛЕ последней правки).
7. MovePlugin из A5 не покрыт (нужен второй процесс и путь `_on_move_to_process_requested`); покрыт только SetPluginConfig.

## Что оставил открытым / ненадёжно

- **Неоднозначность контракта coalescing**: если memo_before у ПЕРВОЙ записи серии = None, а у следующих задан, что
  хранить? Буквально — None (первая). Не тестировал. Аналогично memo_after=None у новейшей. Нужно решение лида.
- Что считать «выбором после операции» для добавления: сейчас presenter новый узел НЕ выбирает; если реализация
  начнёт выбирать добавленный узел, A1/A2 после Повтора могут потребовать другого ожидания. Повтор добавления не тестировал.
- **Break-injection не проводил** (по регламенту это лид). Слабые места, которые я вижу сам: A8 проверяет weakref
  только для memo, выпавших из ЗАПИСЕЙ, но не ловит memo, удерживаемое замыканием/change-callback вне SnapshotHistory
  (это уровень orchestrator'а, тестов там нет); A6 не различает «memo=None» и «memo=пустой выбор» при реализации,
  которая всегда снимает выбор в dispatcher.
- Тесты не проходят через настоящие кнопки Undo/Redo вкладки (только через тот же `services.commands`) и без
  инспектор-панели (`inspector is None` -> plugin_index=0).
- Ordering-риск плана (change-callback идёт ПОСЛЕ перерисовки) косвенно закрыт A1/A3, но отдельного теста порядка нет.
- Утечка: чтение исходников — только `snapshot_history.py`, хелперы тестов, `mutations.py`, `presenter.py`,
  `command_dispatcher.py`, `project.py` (только SetPluginConfig). Это НЕ реализация memo (её нет), но для понимания
  путей вкладки читал; `docs/reviews/*undo-restores*` не открывал.
