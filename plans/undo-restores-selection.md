# undo-restores-selection — «Отмена» и «Повтор» возвращают выбор операции

- **Дата:** 2026-09-30 · **Ветка:** `feat/undo-restores-selection` (от `main` 66cdfd56) · **Статус:** ACTIVE
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

**Acceptance criteria** (Qt, `qtbot`, через те же пути, что кнопки и удаление в вкладке):
- [ ] A1 выбран узел A → добавить процесс B → undo → выбран ровно A, B нет.
- [ ] A2 ничего не выбрано → добавить B → undo → ничего не выбрано.
- [ ] A3 выбран B → удалить B → undo → B есть и выбран ровно B.
- [ ] A4 после A3 → redo → B нет, выбор равен выбору сразу после исходного удаления.
- [ ] A5 выбран B → `SetPluginConfig`/`MovePlugin` на B → undo → выбран B.
- [ ] A6 запись, сделанная `dispatch` в обход вкладки (без memo) → undo → уцелевшие из текущего выбора, без исключений.
- [ ] A7 две правки одного узла с одним `coalesce_key` → один undo → выбор до первой правки.
- [ ] A8 `max_history=N`, N+5 команд → memo не копятся сверх записей (число хранимых memo ≤ записей undo+redo), undo до дна не падает.
- [ ] A9 `SnapshotHistory` без memo ведёт себя побайтно как раньше (существующие тесты `actions_module` зелёные).
- [ ] Радиус зелёный: `multiprocess_framework/modules/actions_module/tests`, `multiprocess_prototype/adapters/dispatch`,
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
