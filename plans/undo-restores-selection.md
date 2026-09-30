# undo-restores-selection — «Отмена» и «Повтор» возвращают выбор операции

- **Дата:** 2026-09-30 · **Ветка:** `feat/undo-restores-selection` (от `main` 66cdfd56) · **Статус:** DONE 2026-09-30
- **Решение владельца 2026-09-30:** «сделай и там и там как лучше и правильнее». Лид выбрал поведение
  Photoshop / Figma / Illustrator / Blender: выбор — часть записи истории. Веб-редактор слоёв (`pult_web`, R-5)
  уже так работает, приводим к нему Qt.

## Контракт (один на веб и Qt)

| Операция → действие | Выбор после |
|---|---|
| выбран A → добавить B → **Отмена** | A (B исчез) |
| ничего → добавить B → **Отмена** | ничего |
| выбран B → удалить B → **Отмена** | B вернулся **и выбран** |
| (после предыдущей строки) **Повтор** | тот выбор, что был сразу после исходного удаления |
| выбран B → правка/сдвиг B → **Отмена** | B |
| запись истории, сделанная ВНЕ этого редактора → **Отмена** | уцелевшие из текущего выбора (как сейчас, G.6.3) |

Отменённый объект не «оживает» под чужим именем. Серия, слитая `coalesce_key`, отменяется одним шагом и
возвращает выбор ДО первой правки серии.

## Соседи

| План | Что там | Что берём / даём | Граница |
|---|---|---|---|
| `2026-05-29_constructor-maturity` P1 (DETAILED, не начат) | один движок команд: domain-dispatch + middleware | даём: `SnapshotHistory` учится хранить непрозрачный memo записи | P1 не трогаем; memo переживёт слияние движков, поле generic |
| `gui-constructor` Task 3.4 (PENDING) | Qt-помощник «черновик + undo-стек словарей» для редактора слоёв | даём: контракт таблицы выше — помощник обязан его соблюдать | 3.4 не начинаем |
| `line-sim-layer-editor` 1.3h-c (DONE) / R-5 | веб-«Отмена» по строкам формы | контракт F2 подтверждён владельцем | веб не меняем; «Повтора» в вебе нет — вне задачи |

## Task 1.1 — выбор в записи истории, вкладка pipeline

**Level:** Middle+ · **Assignee:** tester (слепой, worktree на коммите плана) → developer (Sonnet 5.5) → reviewer (Opus 5.5)
**Goal:** во вкладке pipeline «Отмена»/«Повтор» операции, сделанной из этой вкладки, ставят выбор узлов по таблице контракта.
**Files (ожидаемые):**
- `multiprocess_framework/modules/actions_module/snapshot_history.py` — непрозрачный memo на запись (`record(..., memo=None)`);
  при coalescing — memo первой записи серии для «до», новой — для «после»; доступ к memo отменённой/повторённой записи.
  Qt-free, без app-импортов; старые вызовы без memo работают без изменений.
- `multiprocess_prototype/adapters/dispatch/command_dispatcher.py` (+ `domain/protocols/command_dispatcher.py`, если меняется протокол) —
  прокинуть memo в `dispatch`, отдать его слушателю при `undo`/`redo` ПОСЛЕ `_restore` (после перерисовки по `TopologyReplaced`).
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/{presenter,mutations,_host}.py` — снять выбор до своей команды и
  сразу после перерисовки; при `undo` ставить «до», при `redo` — «после»; записи без memo — прежний путь G.6.3.
- `actions_module/DECISIONS.md` — локальное ADR про memo (затем `python -m scripts.sync`); README/STATUS модуля.

**Зафиксированный API `SnapshotHistory`** (тестер и разработчик пишут против него; остальной дизайн — за разработчиком):
- `record(*, before, after, label, command_type, coalesce_key=None, memo_before=None, memo_after=None)`; при coalescing
  хранится `memo_before` первой записи серии и `memo_after` новой.
- `take_undo_with_memo() -> tuple[T, object | None] | None` — снимок `before` и `memo_before` отменённой записи;
  `take_redo_with_memo() -> tuple[T, object | None] | None` — `after` и `memo_after`. `take_undo()`/`take_redo()` не меняются.
- memo хранятся только внутри записей: обрезка по `max_history` и `clear()` их отпускают.

**Acceptance criteria** (Qt, `qtbot`, через те же пути, что кнопки и удаление в вкладке):
- [x] A1 выбран узел A → добавить процесс B → undo → выбран ровно A, B нет.
- [x] A2 ничего не выбрано → добавить B → undo → ничего не выбрано.
- [x] A3 выбран B → удалить B → undo → B есть и выбран ровно B.
- [x] A4 после A3 → redo → B нет, выбор равен выбору сразу после исходного удаления.
- [x] A5 выбран B → `SetPluginConfig`/`MovePlugin` на B → undo → выбран B.
- [x] A6 запись, сделанная `dispatch` в обход вкладки (без memo) → undo → уцелевшие из текущего выбора, без исключений.
- [x] A7 две правки одного узла с одним `coalesce_key` → один undo → выбор до первой правки.
- [x] A8 `SnapshotHistory(max_history=N)`, N+5 записей с memo → memo вытесненных записей собраны сборщиком мусора
      (`weakref`), undo до дна не падает; то же после `clear()`.
- [x] A9 `SnapshotHistory` без memo ведёт себя побайтно как раньше (существующие тесты `actions_module` зелёные).
- [x] Радиус зелёный: `multiprocess_framework/modules/actions_module/tests`, `multiprocess_prototype/adapters/dispatch`,
      `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests`, `multiprocess_prototype/frontend/tests`.

**Break-injection (лид, предсказания до прогона):**
1. undo игнорирует memo → A1, A3 красные.
2. выбор ставится ДО перерисовки → A1, A3 красные (перерисовка перетирает).
3. при coalescing берётся memo последней записи → A7 красный.
4. redo ставит «до» вместо «после» → A4 красный.
5. memo хранится вне записи (словарь, не чистится при обрезке) → A8 красный.

**Out of scope:** веб-редактор слоёв; другие вкладки (settings/plugins/services — у них нет выбора объектов на холсте);
слияние движков (constructor-maturity P1); «Повтор» в вебе.
**Риски:** `_restore` публикует `TopologyReplaced` синхронно, change-callback идёт после — порядок проверять тестом, не чтением.

## Итог (2026-09-30)

Слепой тестер (Sonnet) `fde79ab2`: 20 красных / 9 зелёных → developer (Sonnet) `09ea9a1c` → инъекции лида → ревью Opus
APPROVE_WITH_NITS → итерация 1 `abc0c875`, `548d4f6a`, `56a7ed5b` → повторное ревью APPROVE_WITH_NITS (оба пункта закрыты в `56a7ed5b`).
Радиус 1570 passed / 8 skipped. Инъекции: 13 из 13 убиты (I1–I10, N2, N4, N4b), наборы красных совпали с предсказаниями,
кроме I4/I6 — ждал красный A4, он зелёный: вкладка не выбирает новые узлы, поэтому «выбор после» сегодня равен
«выбору до минус удалённые», и на уровне Qt подмену не отличить; ловят framework-тест redo, A7 redo и hazard-тест захвата.
Ревью: [`docs/reviews/2026-09-30_undo-restores-selection-task-1.1-review.md`](../docs/reviews/2026-09-30_undo-restores-selection-task-1.1-review.md).

**Открыто:** смешанное удаление (процесс + бокс) = 2 записи истории, одна «Отмена» возвращает выбор последней —
лучше, чем было (пусто), но не весь; одна запись на `remove_selected` — отдельная задача. Живой Qt-стенд не
запускался — доказательство pytest на настоящих `PipelineTab`/`GraphScene`/инспекторе (зонд ревьюера).
