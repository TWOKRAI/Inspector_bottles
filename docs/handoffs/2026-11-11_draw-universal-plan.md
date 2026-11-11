# Handoff 2026-11-11: план draw-universal в main → ревью плана и approve

Продолжение [`2026-11-11_draw-architecture-to-plan.md`](2026-11-11_draw-architecture-to-plan.md). Владелец 2026-11-11:
«в очередь поставь и коммит давай [в main], в новый чат перейду».

## Что уже в `main`

- План [`plans/2026-11-11_draw-universal/`](../../plans/2026-11-11_draw-universal/plan.md): DRAFT, `Plan review: PENDING`, 11 задач.
  - Ф0: 0.1.
  - Ф1: 1.1–1.4.
  - Ф2: 2.1–2.3.
  - Ф3: 3.1.
  - Ф4 (опционально): 4.1, 4.2.
  - Есть `design.md` и `amendments.md`.
  - Бюджет — оценка менеджера: Ф0–Ф3 ~5,0M токенов и ~41 запуск агентов; Ф4 ~1,0M.
- Строка в журнале планов `plans/README.md` (DRAFT).
- Строка очереди владельца `27a` в [`plans/queue/ORDER.md`](../../plans/queue/ORDER.md): первая строка 2.0, задача 0.1.
- Карта группы [`plans/queue/group-draw-dataset.md`](../../plans/queue/group-draw-dataset.md). В ней:
  - состав: draw-universal, dataset-annotation, layer-render, line-sim-layer-editor, letters-retrain, dataset-circle-capture, DS-1;
  - владение;
  - пересечения O1–O11;
  - порядок.

  Обратные ссылки на карту стоят в шапках или в конце планов-членов.
- Входные документы:
  - отчёты CTO r1 и r2;
  - handoff архитектуры;
  - страницы [`docs/diagrams/system-map/`](../diagrams/system-map/index.html).

## Следующий шаг (новый чат)

1. **Ревью плана — раунд 1 есть: CHANGES REQUESTED** (18 замечаний, 5 блокеров; бюджет по ревьюеру ~6,0M / ~48 запусков против 5,0M / 41 в плане) — [`plans/2026-11-11_draw-universal/review-plan-r1.md`](../../plans/2026-11-11_draw-universal/review-plan-r1.md).
   - Заново ревью **не запускать**. Передать список `manager` (`model: opus`, `effort: xhigh`) на одну итерацию правок; потом ревью раунд 2 (свежий `reviewer`, `model: sonnet`, с файлом r1 и диффом).
   - Замечание 16 (объём conformance и фильтров `ItemTemplate`) — вопрос владельцу, не менеджеру.
   - Замечание 9: до Task 1.1 лид дописывает поправку в `plans/2026-10-18_camera-device-service` Task 3.4 (убрать `overlay_draw/plugin.py` из её FILES).
2. **Вопросы владельцу.** Задать В1–В4 из `plan.md`:
   - **В1.** DejaVu в репозиторий: два файла, 704 128 и 756 072 байт; `LICENSE_DEJAVU` рядом в matplotlib (ревьюер проверил наличие). Задать **при approve** (замечание 12), с веткой «нет».
   - **В2.** Свести `dataset-annotation` с `Services/labeling` в один пакет.
   - **В3.** Экспорт:
     - перевод фигур в YOLO/COCO — `Services/draw/export.py`;
     - снимок датасета — сервис датасета.
   - **В4.** Сбор кадров — `frame_saver` вместе с DS-1, а не новый `dataset_capture`.
3. **Approve.**
   - Выполнить `python3 scripts/plans_ledger.py approve plans/2026-11-11_draw-universal`.
   - Поле `Plan review` заполнять в момент approve.
   - После approve план менять только строкой в `amendments.md` и вызовом `plans_ledger.py amend`.
4. **Ветка и старт.**
   - Создать worktree от `main`: `git worktree add -b feat/draw-universal .claude/worktrees/draw-universal main`.
   - Первая задача: `/dev:implement Task 0.1` (замеры).
   - Проверить, доступен ли Orin; если нет, так и записать.

## Открыто и ненадёжно

- В основном дереве (ветка `docs/atlas-pilot-1111`, чужая полоса) остались незакоммиченные копии тех же файлов. Они совпадают с `main`:
  - `plans/2026-11-11_draw-universal/`;
  - `plans/queue/group-draw-dataset.md`;
  - правки шапок 5 планов и `ORDER.md`;
  - `docs/diagrams/*`;
  - отчёты CTO и handoff.

  После ревью их надо откатить или удалить по списку из этого раздела. Прежде чем удалять, сверить с `git diff main -- <путь>`. Чужие файлы в дереве не трогать: память, `backlog.md`, `stage0-eval.md`, два handoff, `feedback_allowedtools…`.
- Страница `draw-before-after.html`: 17 правок из CTO r2 §4 не внесены.
- Счётчик тестов `overlay_draw`: 30 по grep против 26 в handoff. Число для приёмки Task 1.1 снимается прогоном.
- Прогресс `layer-render`: 15/22 по маркерам против 13/22 в `ORDER.md`. Не сверено с git.
- Пересмотр `layer-render` вместе с `line-sim-layer-editor` (O1–O5) — после Ф1 этого плана.
- План DS-1 не написан, пока только кандидат в `backlog.md`. Баги `frame_saver` не заведены, список — в handoff архитектуры.
