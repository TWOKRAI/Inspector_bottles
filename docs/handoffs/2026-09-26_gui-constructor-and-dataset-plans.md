# Handoff: конструктор GUI и датасет — планы написаны и прошли ревью (2026-09-26)

**main:** `2d6a7f64`, дерево чистое (кроме этого файла). Кода в сессии нет — только решения, планы, ревью.
**Порядок работ — один источник:** блок «▶ ТЕКУЩИЙ ПОРЯДОК» в начале [`plans/QUEUE.md`](../../plans/QUEUE.md).

## Что сделано

| Что | Где | Коммит |
|---|---|---|
| Решение владельца: фреймворк = конструктор, `Services` = срезы с пакетами виджетов, прототип тонкий; эталоны `minimal_app` + `minimal_gui`; Пульт = виджет ручек (адрес общий с `backend_ctl`); `apps/pult` → `apps/gui_client`; симулятор — вкладкой; разметка датасета | [`frontend-constructor/constructor-layers.md`](../../plans/frontend-constructor/constructor-layers.md) | `0c7a460e`, `92c3d14f`, `e3f47c40` |
| Ревью CTO направления — ACCEPT WITH CONDITIONS | [`docs/reviews/2026-09-26_gui-constructor-layers-cto.md`](../reviews/2026-09-26_gui-constructor-layers-cto.md) | `57d6b0fd` |
| План `gui-constructor`: 3 файла дизайна (замена T4.1) + 5 фаз | [`plans/gui-constructor/plan.md`](../../plans/gui-constructor/plan.md) | `3e5f67a6` |
| План `dataset-annotation`: context + 5 фаз (обучение — облако, вне плана) | [`plans/dataset-annotation/plan.md`](../../plans/dataset-annotation/plan.md) | `3e5f67a6` |
| Синхронизация соседей: gui-service (`apps/pult` 27 → 4, остаток — запись решения), frontend-constructor Ф4/Ф5 перенесены, rework 2б.2, редактор слоёв — вкладкой | — | `3e5f67a6` |
| Ревью CTO обоих планов и порядка — ACCEPT WITH CONDITIONS; три блокирующие правки внесены | [`docs/reviews/2026-09-26_gui-constructor-dataset-plans-cto.md`](../reviews/2026-09-26_gui-constructor-dataset-plans-cto.md) | `2d6a7f64` |
| Страница-пояснение со схемами (приватная) | https://claude.ai/artifact/UoDWrLzyYwNLy6JnHBfkWL | — |

## Следующий шаг — за владельцем

1. **Approve** `gui-constructor` и `dataset-annotation` (оба DRAFT). После approve — строки в ledger (`plans_ledger.py status --check` сейчас `WARN MISSING_ROW` для обоих).
2. **Ответы на открытые вопросы** (у каждого в плане есть рекомендация):
   - gui-constructor `plan.md` → «Открытые вопросы»: явно утвердить Р-A/B/C/D/F бывшего T4.1 (нужно до Task 1.3/1.4); команда `backend_ctl` для набора ручек Пульта; миграция геометрии `INNOTECH/Inspector`.
   - dataset-annotation `plan.md` → «Открытые вопросы»: тип задачи (рекомендация — рамки + класс снимка); где живёт датасет (рекомендация — Orin); PNG или JPEG; бюджет диска; заморозить ли `ml_train_section`; трогать ли секции `dataset_gen` / «Вырез эталона».
3. **Корневой `CLAUDE.md`** утверждает «Ultralytics YOLO … extras `[ml]`» — неверно (`import ultralytics` → `ModuleNotFoundError`, в `pyproject.toml` только комментарий). Не правлено без слова владельца.

## После approve — с чего начинать (полосы QUEUE)

- **И1:** gui-service 1b.2c (вердикт бэкенда до формы) ∥ 1b.2d — не заблокированы.
- **И2:** gui-constructor Task 1.0 (правила слоёв: `examples ↛ Services/Plugins` в sentrux + контракт-тест `Services ↛ Qt` кроме `gui/`) → 1.1 характеризация (+ замер `create_tabs` как якорь для 200 мс).
- **Д1:** dataset Task 1.1 вертикальный срез (без GUI, без стенда) ∥ разведка Step 1 задачи 3.1 (`investigator`, чтение).
- **Ф:** transport-single-policy Ф4 (L-6) между продуктовыми задачами.
- Канон на каждой задаче: тестер в worktree до кода → реализация → инъекции лида → стенд → ревьюер синхронно.

## Открыто / ненадёжно

- Ничего не запускалось живьём: литералы FrameHub 50/200 мс, `restoreState`, веер кадров — предварительные; ловит ли sentrux внешний `to = "PySide6/*"` — проба Task 1.0.
- Процесс `dataset` во фрагменте `topology/dataset.yaml`: WAL с двумя писателями и fork-safety `SQLManager` не проверялись.
- Ограничение модели: агент `plan-dataset-annotation` упёрся в недельный лимит на середине правок; остаток правок (фрагмент вместо `base.yaml`, ссылки +2) доделан лидом и сверен грепом, абзац «Канал файлов» сверен md5 — совпадает в обоих планах.
- Долги документов выше бюджета 32 КБ: `QUEUE.md` (~165 КБ), `frontend-constructor/plan.md` (55 КБ), `gui-service/phase-1-one-machine.md` (54 КБ), `phase-1b-recipe-service.md` (38 КБ), `lifecycle-stop-ownership.md` (44 КБ), `gui-bootstrap-design.md` (44 КБ, теперь история).
- Старые worktree ждут решения: `gui-1b2b-pre{,-tester}`, `lso-1.4…1.6-*`, `lso-hotfix` (ветки слиты).
