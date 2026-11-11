# Группа планов: рисование, разметка, датасет, синтетика, обучение

> Создано 2026-11-11 по просьбе владельца: «собрать группу, чтобы не потерять планы, и согласовывать между ними».
> **Порядок работ** по-прежнему задаёт [`ORDER.md`](ORDER.md). Этот файл — карта группы: кто в неё входит, кто чем
> владеет и где планы пересекаются.
> **Правило группы.** План, который меняет общий модуль, формат или контракт из таблицы «Пересечения», правит строку
> здесь в том же коммите и ставит обратную ссылку в план-соседа (память: «Новый план — среди соседей»).
> Опись 2026-11-11 сделана по маркерам в планах и `ORDER.md` от 10-03; с git не сверена.

## Состав

| План | Статус (на 2026-11-11) | Чем владеет | Связь в группе |
|---|---|---|---|
| [`2026-11-11_draw-universal`](../2026-11-11_draw-universal/plan.md) | APPROVED 2026-11-11, 0/12 | `Services/draw`, плагин `overlay_draw` (замена `circle_draw`, `contour_draw`, `render_overlay`, подписи `ml_inference`) | нижний слой рисования для всех; основание — [handoff](../../docs/handoffs/2026-11-11_draw-architecture-to-plan.md) и отчёты CTO 2026-11-11 |
| [`dataset-annotation`](../dataset-annotation/plan.md) | DRAFT, 0/17, кода нет; CTO: ACCEPT WITH CONDITIONS; **В2: один пакет с `Services/labeling`** — пересобрать после DS-1 | `Services/dataset` (новый), виджет разметки, захват, экспорт YOLO | разметка и датасет; пересекается с `Services/labeling` из CTO r2 |
| [`layer-render`](../layer-render/plan.md) | APPROVED 10-01; 15/22 по маркерам плана, 13/22 в `ORDER.md` (10-03) — не сверено | `Services/layer_render`, веб-редактор (Ф5), обучение на синтетике (Ф6), шрифты (Ф7), регионы (Ф9 IDEA) | строится на `draw` (решение владельца 11-11); план **пересмотреть** после `draw-universal` |
| [`line-sim-layer-editor`](../line-sim-layer-editor/plan.md) | APPROVED 09-27, 8/10 | редактор слоёв сима, `pult_web`, `layer_preview` | тот же редактор, что `layer-render` Ф5 (O1) |
| [`letters-retrain`](../letters-retrain/plan.md) | IN PROGRESS, 2/3 | `ml_train` для букв, пресеты `dataset_gen` | потребитель синтетики и экспорта |
| [`dataset-circle-capture`](../dataset-circle-capture.md) | часть 1 DONE | `center_crop`, рецепт сбора, `frame_saver` в рецепте | поставщик реальных кадров |
| DS-1 — [`dataset-sidecar-truth`](../2026-11-11_dataset-sidecar-truth/plan.md) | DRAFT 2026-11-11, 0/6 активных + 4 DEFERRED (реальные кадры — DS-В4), решения DS-В1…DS-В4 у владельца | регистры `frame_saver` `sidecar_keys`, `sidecar_source` (DEFERRED: `save_when`, `min_free_mb`, `subfolder_template`); журнал истины `scene_source`; `Services/line_sim/tools/join_frame_truth.py` (`training_label` — машинная метка); `model_id`/`angle_symmetry` у `ml_inference` | берёт чистый кадр и `draw_overlay: false` (draw-universal 3.1); DEFERRED-часть — `get_path` (1.4) и `bucket`/`safe` (внутри 5.1); даёт пары с истиной letters-retrain и сервису датасета; текст кандидата — `backlog.md` (правка другой сессии, в `main` нет) |
| [`line-sim-belt-look`](../line-sim-belt-look/plan.md) | DONE | — | для справки |
| [`draw-mode-rework`](../draw-mode-rework/plan.md) | — | робот-плоттер | **не входит**: совпадение имени |

## Пересечения (решения владельца 2026-11-11 — в `draw-universal/plan.md`, decisions log)

| # | Что | Где | Предложение |
|---|---|---|---|
| O10 | `dataset-annotation` учит на кадре с оверлеем `render_overlay.rendered_frame`; `draw-universal` Ф3 и DS-1 сохраняют чистый кадр | `dataset-annotation/plan.md:100`; `backlog.md:96,111` | учить на чистом кадре; оверлей — только показ. DS-1 Task 2.3 — после draw-universal 3.1; приёмка: `.png` == выход `center_crop` |
| O8 | Сохранение кадров: новый `dataset_capture` против расширения `frame_saver` | `dataset-annotation/phase-3-capture.md:18,38`, `context.md:14`; `backlog.md:87-89,102`; `dataset-circle-capture.md:28` | **решено (draw-universal В4):** `frame_saver` с DS-1, один писатель пар «кадр + `.json`»; имя можно сменить. DS-1: `join_frame_truth` только дописывает ключи `truth`/`pred`/`delta_angle_deg`/`hard` в готовый `.json` (атомарно), пар не создаёт и не переносит (`2026-11-11_dataset-sidecar-truth/design.md` §4) |
| O6, O7 | Экспорт в `ml_train` и YOLO/COCO описаны в двух местах | `layer-render/plan.md:123-131,156-157`; `dataset-annotation/plan.md:54,166`, `phase-1-dataset-service.md:69`, `phase-4-quality-export.md:108,123` | **решено (В3):** фигуры → YOLO/COCO в `Services/draw/export.py`, раскладка папок — сервис датасета |
| O9 | `overlay_draw` правили четыре плана: вход `image/*`, побайтная копия кадра, необязательный `overlay` | `code-reader-gui.md:35,46,49`; `2026-10-18_camera-device-service/tasks/3.4.md:6,17,20`; `topology-port-join.md:9`; `dataset-circle-capture.md:29` | `draw-universal` сохраняет эти контракты — в приёмке задач. camera-device-service 3.4 ещё PENDING: правило копии кадра входит в draw-universal Task 1.1, а 3.4 убирает `overlay_draw/plugin.py` из своих FILES (`draw-universal/design.md` §4) |
| O11 | `word_layout` + `sidecar.track_id` / `frame_id` | `backlog.md:88,101`; `word-layout/tasks/C-32.md:1,17`; `letter-robot-cycle/plan.md:138,216` | DS-1: для датасета не нужно — `.json` несёт `track_id`/`frame_id` от `center_crop` и ответ `ml_inference`; строка журнала — контракт скрипта α; `2026-11-11_dataset-sidecar-truth` Task 3.2 DEFERRED (DS-В4) |
| O12 | Истина сима для пар: на кадре не едет (MJPEG, решение line-sim 2026-09-21 п.4, тест `test_scene_source_hazards.py:408`) | `plans/line-sim/plan.md:228-231`; `2026-11-11_dataset-sidecar-truth/design.md` §1–§3 | DS-1 (DS-В1): журнал JSONL в `scene_source` + офлайн-сведение `match_job`; прототип про сим не знает |
| O1–O5 | Синтетика: один веб-редактор в `pult_web` у двух планов, Qt `sim.*`, `line_sim/core/factory.py`, `letters_layered.yaml`, `dataset_gen` | `layer-render/phase-5-editor.md:21`, `plan.md:121`, `phase-2-core-2.4b.md:24`; `line-sim-layer-editor/phase-1-canvas-html.md:34`, `phase-1-qt.md:5`, `phase-1-engine.md:16,86` | решить при пересмотре `layer-render` |

## Порядок внутри группы (предложение, до решения владельца)

1. `draw-universal` Ф0–Ф3 (Ф4 по желанию) — путь показа, чистый кадр.
2. Параллельно, если хватает писателей: DS-1 ([`dataset-sidecar-truth`](../2026-11-11_dataset-sidecar-truth/plan.md)) — 0.1, 1.1a, 1.1b и 2.1 ∥ draw-universal Ф1–Ф2; 1.1c после них; 2.3 после draw-universal 3.1 (тот же рецепт, не в одной волне). Реальные кадры (2.2, 2.4, 3.1, 3.2) — DEFERRED до DS-В4: 2.2 ждёт draw-universal 1.4, 3.1 — `bucket`/`safe` из 5.1.
3. Сведение `dataset-annotation` с `labeling` из CTO r2: одно решение по O6–O10, потом её Ф1.
4. Пересмотр `layer-render` вместе с `line-sim-layer-editor` (O1–O5; Ф7 шрифты, Ф9 регионы = фигуры `draw`, LR-001).
5. `letters-retrain` Ф1 — по готовности синтетики и экспорта.
