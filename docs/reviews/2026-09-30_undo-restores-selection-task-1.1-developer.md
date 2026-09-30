# Task 1.1 — developer report (undo/redo возвращают выбор узлов)

Ветка `feat/undo-restores-selection`. План: `plans/undo-restores-selection.md`.

## Что сделано
- `SnapshotHistory`: `memo_before/memo_after` в `_Snapshot` и `record`, `take_undo_with_memo` / `take_redo_with_memo`;
  coalescing: `prev.memo_before` дословно + новый `memo_after`; `take_undo/take_redo` — обёртки.
- `CommandDispatcherOrchestrator.dispatch(view_state=)`: memo до apply и после публикации событий; ошибка
  `view_state` логируется, memo=None. `add/remove_view_restore_listener`; `undo/redo`: `_restore` -> слушатели (только при memo != None) -> `_notify_change`.
- Protocol `CommandDispatcher.dispatch` получил необязательный `view_state`.
- Pipeline: `PipelineSelectionMemo`, `capture_selection_memo`, `_on_view_restore` (в `_block_signals`, `clearSelection` + `_restore_selection`), регистрация/снятие слушателя (`dispose`).
- `mutations.py`: все 10 `commands.dispatch(` -> `self._dispatch(cmd, **kw)` (+ `view_state=host.capture_selection_memo`); `_host.py`: `capture_selection_memo`.
- ADR ACT-003, README/STATUS actions_module. `scripts.sync` ничего не перегенерировал (ACT-* нет в глобальном DECISIONS).
- Hazard-тесты: `multiprocess_prototype/adapters/tests/test_hazards_view_state_memo.py` (6).

## Отклонения / оговорки
- Тронут `multiprocess_prototype/domain/tests/_fakes.py` (`FakeCommandDispatcher.dispatch` принимает `view_state`) — сломались 6 pipeline-тестов; брифом разрешено.
- Hazard-тесты положены в `adapters/tests/` (там существующие тесты диспетчера), а не в `adapters/dispatch/`.
- Тесты слушателей на реальной сцене не написаны — их покрывают приёмочные reds.
- `remove_selected` из нескольких команд по-прежнему несколько записей истории (вне scope): memo первой записи — выбор до удаления, но одна Отмена откатывает лишь последнюю.

## Радиус
`actions_module/tests + prototype/adapters + pipeline/tests + prototype/frontend/tests`: 1223 passed, 3 skipped. Расширенный (+ `domain`): 1344 passed, 5 skipped. ruff check/format — чисто.

## Итерация 1 (правки по ревью: nits 1, 2, 4)

- N1: `add_view_restore_listener` / `remove_view_restore_listener` вынесены в Protocol `CommandDispatcher`; `FakeCommandDispatcher` держит реальный список `view_restore_listeners` (undo в fake не симулируется, слушателей не зовёт). `PipelinePresenter` регистрирует напрямую в `__init__`, снимает напрямую в `dispose()`; `getattr` и флаг `_view_restore_registered` удалены.
- N2: `test_teardown.py::TestPresenterDispose::test_dispose_unregisters_view_restore_listener_on_real_dispatcher` -- реальные orchestrator-сервисы, слушатель в `_view_restore_listeners` (приватный список, публичного геттера нет), снят после `dispose()`, второй `dispose()` не бросает.
- N4: `_describe_cb(cb)` в `command_dispatcher.py` (не бросает), `%s` вместо `%r` в `_apply_memo` / `_notify_change`; два hazard-теста с `_HostileCallback` (падают вызов, `__repr__`, `__getattr__`).
- Своя break-injection (до сдачи лиду): `%r` вместо `_describe_cb` -> 2 N4-теста красные; удалить remove в `dispose()` -> N2-тест красный (3 failed / 19 passed на двух файлах). Файлы восстановлены, `git diff` чистый от инъекций.
- Радиус: 1569 passed, 8 skipped. ruff check / format --check чисто.
