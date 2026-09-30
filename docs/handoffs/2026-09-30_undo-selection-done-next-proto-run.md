---
date: 2026-09-30
topic: «Отмена» возвращает выбор (веб + Qt) — готово; каталог букв пересобран; дальше прогон прототипа на кадре сима
machine: Windows
branch: feat/undo-restores-selection → main (fast-forward, если сосед дал «ок»)
---

## Session goal

Продолжить line-sim по `2026-09-30_line-sim-r5-r6-stroke-next-proto-run.md`, договориться с соседней сессией,
закрыть открытые вопросы владельца. По ходу владелец попросил одно правильное поведение «Отмены» в вебе и в Qt.

## Done

- **Сосед `inspector-bottles-68`** (transport-f4, владеет основным деревом и `feat/qr-code-reader`; задачи 4.8a → 4.7 → 4.8b).
  Договорённость: основное дерево не трогаем; перед каждым движением `main` — SHA и «ок» друг от друга; перед его
  `measure` гасим functional и не гоняем тесты. Его 4.7 поменяет дефолты рецептов процесса (`frame_ring_depth`,
  `overflow`) — перед слиянием он пришлёт ветку, мы прогоняем `letter_robot_sim` и отдаём числа.
- **Каталог букв пересобран** по рецепту `Services/line_sim/presets/README.md`, но **кириллицей А/К/Р/Х**: классификатор
  `mobilenet_v3_large_20260616_050828` знает только кириллицу, старый `letters_ink` был латиницей A/K/P/X (имена классов
  не совпали бы). 4 класса × 9 спрайтов (DejaVu + Mono со штрихом 0–3, Bold). Лежит ТОЛЬКО в worktree
  `.claude/worktrees/merge-main/data/line_sim/letters_ink` (+ `letters_ink_disk.png`); старый — рядом `letters_ink_v1_latin`,
  `letters_ink_disk_v1.png`. Туда же скопированы `data/models`, `belt_tile.png`, `belt_photo_full.png`. Стенд-worktree не трогали.
- **F2 / «Отмена» — решение владельца «как лучше и правильнее»:** выбор — часть записи истории (Photoshop/Figma/Blender).
  Веб (`pult_web`, R-5) уже так работал — подтверждён. Qt приведён к тому же: план `plans/undo-restores-selection.md` (DONE),
  memo выбора в `SnapshotHistory` (ACT-003), `CommandDispatcher.dispatch(view_state=)` + слушатели восстановления вида,
  вкладка pipeline. Слепой тестер (Sonnet) → developer (Sonnet) → 13/13 инъекций → ревью Opus ×2 APPROVE_WITH_NITS. Радиус 1570 passed.
- Память: `feedback_agent_models_sonnet_impl_opus_review.md` (реализация Sonnet 5.5, ревью Opus 5.5),
  `feedback_stand_lock_check_must_gate_the_command.md`.

## What did NOT work

- **Проверка замка рядом с pytest не гейтит.** Ревьюер делал `cat stand.lock; pytest` одной командой — ~5.7 с тестов попали
  в первый кейс замера соседа (16:50:46). Соседу сказано, он перемеряет. Теперь в брифах только
  `[ ! -e /d/PROJECT_INNOTECH/Inspector_vision/stand.lock ] && pytest … || echo "STAND LOCKED — skipped"`.
- Хук `lint-brief` отвергает бриф без полей DESIGN/FILES/REDS/REPORT и с FILES > 6 — форма `.claude/plugins/dev/templates/executor-brief.md`,
  исключение строкой `BRIEF-OVERRIDE: <причина>`. В шаблоне TEST RULES есть `uv sync` — в этом проекте запрещено, писать своё.
- Моя первая рекомендация по F2 («как все редакторы») не учитывала Qt-механизм владельца; сверять с тем, что уже есть в продукте.

## Next step

Прогнать прототип (детектор + ML) рецептом `letter_robot_sim.yaml` на живом кадре сима с новым кириллическим каталогом и
записать числа (круги / буква / класс против ожидаемого). Из `.claude/worktrees/merge-main` (там данные):
1. Спросить соседа, нет ли `measure`; записать `stand.lock` (functional, порты 8766/8092/8091/8765), сообщить соседу.
2. Сим: `FW_SHM_OWNER_INCARNATION=1 BACKEND_CTL=1 BACKEND_CTL_PORT=8766 MULTIPROCESS_LOG_DIR=<tmp> PYTHONPATH=$PWD ../../../.venv/Scripts/python.exe apps/line_sim/run.py`.
3. Прототип: `FW_SHM_OWNER_INCARNATION=1 BACKEND_CTL=1 PYTHONPATH=$PWD ../../../.venv/Scripts/python.exe multiprocess_prototype/run.py letter_robot_sim`.
4. Истина сима: команды `truth.status` / `truth.reset` плагина `scene_source` (метрики `truth_caught/missed/false_alarm`) —
   они про захват, **не про класс**; класс сверять отдельно (ожидаемый класс спрайта vs ответ `ml_inference`).
5. Погасить: `BackendDriver(host='127.0.0.1', port=8766).system_command({'cmd': 'system.shutdown'})`, удалить lock, сообщить соседу.
Нет `config/calibration/cam0.yaml` → `pick_xy` не выдаётся, робот не берёт диск — для чисел детекции/классов не мешает.
`merge-main` — detached; перед прогоном `git -C .claude/worktrees/merge-main checkout --detach main`.

## Open (ждут владельца)

1. Временная папка `C:/Users/INNOTECH/AppData/Local/Temp/cat_aug_155948` — удалить руками (`rm -rf` запрещён).
2. Пересобирать ли каталог и в `.claude/worktrees/stand` / `ls-look` (сейчас там латиница) — после прогона.
3. `remove_selected` с процессом и боксом = 2 записи истории; одна «Отмена» возвращает выбор последней. Склеить в одну — отдельная задача?

## Unreliable

- «Отмена» в Qt проверена pytest на настоящих `PipelineTab`/`GraphScene`/инспекторе, не руками в приложении.
- `memo_after` на уровне Qt пока не отличим от «выбор до минус удалённые» (вкладка не выбирает новые узлы) — защищён тестами диспетчера.
- Каталог букв: визуально спрайты не просматривались, только счёт файлов; классификатор на них ещё не гонялся.

## Environment

- Worktree: `undo-sel` (ветка `feat/undo-restores-selection`, влита), `undo-sel-tester` (`tests/undo-sel-blind`, отработан),
  `merge-main` (detached, данные сима и модели). Отработанные можно удалить после проверки `git merge-base --is-ancestor <b> main`.
- Скрипт инъекций (scratchpad прошлой сессии, может не пережить): матрица I1–I10, N2, N4, N4b по `inject_undo.py`.
- `main` не запушен.
