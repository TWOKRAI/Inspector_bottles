# Ревью Task 1.1 — undo-restores-selection (09ea9a1c)

**Ревьюер:** reviewer (Opus 5.5), синхронно, 2026-09-30. Файл записан лидом со слов ревьюера (у роли нет Write).
**Вердикт:** APPROVE_WITH_NITS — блокеров и major нет.

## Воспроизведено

- `pytest actions_module/tests + test_acceptance_snapshot_memo + test_acceptance_undo_selection + test_hazards_view_state_memo
  + adapters/tests/test_command_dispatcher` → `108 passed`; Qt-приёмка 11/11, hazard 6/6.
- Зонд на настоящем `PipelineTab` (presenter + scene + inspector) и настоящем orchestrator, `4 passed`:
  - P1: выбран `proc.blur` → удалить с тулбара → undo → выбор `["proc.blur"]`, `inspector.current_process == "proc"`.
  - P2: правка `k=99` на `cam` → клик по `proc` → undo → выбран `cam`, последний `show_plugin_node == ("cam.capture", {"k": 1})`.
  - P2b: то же без клика — тот же результат.
  - Вывод: выбор доходит до инспектора как клик пользователя — `_block_signals` ставит только `_suppress`,
    а `tab._on_selection_changed` (tab.py:284, :531) этим флагом не закрыт. Путь `show_display_node` не проверен.

## Находки

1. **[minor] Протокол без методов слушателя** — `presenter.py:180-186`, `:206-209`. В `CommandDispatcher` (Protocol) добавлен только
   `view_state`; `add/remove_view_restore_listener` presenter ищет через `getattr`. Вход: presenter на `make_pipeline_services`
   (`FakeCommandDispatcher`) → `_view_restore_registered=False`, функция молча выключена; `test_teardown.py` ходит только по этой
   ветке. Исправление: оба метода — в Protocol и Fake, вызов напрямую.
2. **[minor, по чтению] Снятие слушателя в `dispose` не покрыто** (`presenter.py:206-210`). Прогноз: удаление этих строк не убьёт
   ни одного теста (прогнать не смог — замок стенда). Последствие: presenter живёт всё время приложения (dispatcher держит
   bound-метод). Исправление: тест dispose → `_view_restore_listeners == []` / weakref + gc.
3. **[info, по чтению] Смешанное удаление** (процесс + привязанный бокс) = 2 записи истории; один undo ставит memo_before последней —
   часть выбора. Раньше выбор был пуст — стало лучше, регрессии нет. Одна запись на `remove_selected` — вне scope.
4. **[старое, вне diff; новый код повторяет шаблон]** `command_dispatcher.py:326` `logger.exception("... %r", cb)`: если колбэк —
   метод удалённого Qt-объекта, `repr` бросает внутри `except`, и dispatch падает. Зонд P4: `RuntimeError: Internal C++ object
   (DiffScrollTabLayout) already deleted` (колбэк `_refresh_undo_redo`; вкладка разрушена dispose + deleteLater, не как в проде).
   Новый `_apply_memo` (:318) повторяет шаблон. Для `PipelinePresenter` (Python-объект) `repr` безопасен.

FOCUS 2: в pipeline все dispatch — через `_dispatch` (mutations.py:88). Вне вкладки: control_panel/presenter.py:155 (без memo, путь
G.6.3 = A6), recipes presenter.py:390/550 (`undoable=False`). `_apply_memo(None)` выходит сразу.
FOCUS 4: `view_state` не передаётся объектам, которые его не принимают.
FOCUS 6: ACT-003 соответствует коду; «гарантировано/невозможно» в diff нет.

## Открыто / ненадёжно

- **Нарушение правила стенда:** один прогон зонда (~5.7 с) пересёкся с началом measure соседа (-68, лок 16:50:46). Лок проверялся
  в той же команде, но цепочку не остановил. Соседу сообщено.
- Матрицу инъекций лида не перепрогонял; радиус `pipeline/tests`, `frontend/tests` целиком не гонял; pyright не запускал.
- Вывод зондов P3/P4 обрезан — FOCUS 3/5 по чтению.

## Итерация 1 (abc0c875, 548d4f6a) — APPROVE_WITH_NITS

Находки 1, 2, 4 закрыты: `718 passed` по всем потребителям протокола, pyright 0 errors; инъекция «не снимать слушателя» →
ровно 1 красный (teardown-тест); `_describe_cb` не бросает на методе удалённого QObject, partial, lambda, падающем
`__getattr__`/`__getattribute__`. Новые пункты: правка `548d4f6a` без теста; импорт помощника из соседнего тестового
модуля — оба закрыты лидом в `56a7ed5b` (инъекция N4b → ровно новый тест красный).
