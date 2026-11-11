# Handoff 2026-11-11: план draw-universal в main → ревью плана и approve

Продолжение [`2026-11-11_draw-architecture-to-plan.md`](2026-11-11_draw-architecture-to-plan.md). Владелец 2026-11-11:
«в очередь поставь и коммит давай [в main], в новый чат перейду».

## Что уже в `main`

- План [`plans/2026-11-11_draw-universal/`](../../plans/2026-11-11_draw-universal/plan.md): DRAFT, 11 задач.
  - Ф0: 0.1. Ф1: 1.1–1.4. Ф2: 2.1–2.3. Ф3: 3.1. Ф4 (опционально): 4.1, 4.2.
  - Есть `design.md` и `amendments.md` (таблица бюджета — §1).
  - Два раунда ревью плана, оба CHANGES REQUESTED: [r1](../../plans/2026-11-11_draw-universal/review-plan-r1.md) — 18 замечаний, [r2](../../plans/2026-11-11_draw-universal/review-plan-r2.md) — 6 блокеров и 7 мелких. Все правки внесены тремя агентами Sonnet по файлам. Третьего раунда нет (`/dev:plan`).
  - Бюджет: Ф0–Ф3 ~6,2M токенов (5,4–7,0M), ~49 запусков; Ф4 ~1,1M.
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

1. **Ревью плана закончено** (r1 и r2, см. выше). Повторно не запускать.
   - Правило копии кадра — в Task 1.1. Владелец полосы camera-device-service правит её Task 3.4 через `amend`. 1.1 стартует после этой записи или после подтверждения, что 3.4 раньше не стартует. Если 3.4 придёт первой, 1.1 берёт её базу `test_overlay_copy.py`.
2. **Вопросы владельцу** — В1–В5 в `plan.md`, задать при approve:
   - **В1.** DejaVu в репозиторий (два файла, 1,46 МБ). Умолчание — да. Ветка «нет» расписана в В1 построчно.
   - **В2.** `dataset-annotation` и `Services/labeling` — один пакет.
   - **В3.** Экспорт: перевод фигур — `Services/draw/export.py`; раскладка — сервис датасета.
   - **В4.** Сбор кадров — `frame_saver` вместе с DS-1.
   - **В5.** Conformance [Ф6] в 1.3 и фильтры `bucket`/`safe` в 1.4: оставить или отложить. `auto` остаётся при любом ответе.
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
- После r2 не проверено: `SystemBuilder.from_manifest(...).build()` без железа для `color_inspect`, `dataset_circle_capture`, `hikvision_letter_robot`; потокобезопасность `FreeTypeFont`; скорость смешивания патча против цели ≥ 3×. Это проверяется на стадии 0 задач 1.2, 2.2 и 3.1.
- `cv2.putText` ставит точку привязки внизу слева, а патч в 1.2 — вверху слева. Подписи сядут ниже, подстроить на стенде.
- Размеры у предела: `tasks/1.1.md` 8038, `1.2.md` 8085 из 8192 байт. Следующую правку в них переносить в приложение.
- Карта группы: ссылка O8 `dataset-circle-capture.md:28`, возможно, указывает не на ту строку. Ошибка была до плана.
