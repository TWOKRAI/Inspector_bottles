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
| [`2026-11-11_draw-universal`](../2026-11-11_draw-universal/plan.md) | DRAFT, пишется | `Services/draw`, плагин `overlay_draw` (замена `circle_draw`, `contour_draw`, `render_overlay`, подписи `ml_inference`) | нижний слой рисования для всех; основание — [handoff](../../docs/handoffs/2026-11-11_draw-architecture-to-plan.md) и отчёты CTO 2026-11-11 |
| [`dataset-annotation`](../dataset-annotation/plan.md) | DRAFT, 0/17, кода нет; CTO: ACCEPT WITH CONDITIONS | `Services/dataset` (новый), виджет разметки, захват, экспорт YOLO | разметка и датасет; пересекается с `Services/labeling` из CTO r2 |
| [`layer-render`](../layer-render/plan.md) | APPROVED 10-01; 15/22 по маркерам плана, 13/22 в `ORDER.md` (10-03) — не сверено | `Services/layer_render`, веб-редактор (Ф5), обучение на синтетике (Ф6), шрифты (Ф7), регионы (Ф9 IDEA) | строится на `draw` (решение владельца 11-11); план **пересмотреть** после `draw-universal` |
| [`line-sim-layer-editor`](../line-sim-layer-editor/plan.md) | APPROVED 09-27, 8/10 | редактор слоёв сима, `pult_web`, `layer_preview` | тот же редактор, что `layer-render` Ф5 (O1) |
| [`letters-retrain`](../letters-retrain/plan.md) | IN PROGRESS, 2/3 | `ml_train` для букв, пресеты `dataset_gen` | потребитель синтетики и экспорта |
| [`dataset-circle-capture`](../dataset-circle-capture.md) | часть 1 DONE | `center_crop`, рецепт сбора, `frame_saver` в рецепте | поставщик реальных кадров |
| DS-1 — [`backlog.md`](backlog.md) «Кандидат 2026-11-11 … DS-1» | кандидат, плана нет | раскладка кадров `frame_saver` по папкам (буква / «не распознана» / угол) | делит `ItemTemplate`/`get_path` с `draw-universal`; баги `frame_saver` — в handoff |
| [`line-sim-belt-look`](../line-sim-belt-look/plan.md) | DONE | — | для справки |
| [`draw-mode-rework`](../draw-mode-rework/plan.md) | — | робот-плоттер | **не входит**: совпадение имени |

## Пересечения (открыты; решение — владелец)

| # | Что | Где | Предложение |
|---|---|---|---|
| O10 | `dataset-annotation` учит на кадре с оверлеем `render_overlay.rendered_frame`; `draw-universal` Ф3 и DS-1 сохраняют чистый кадр | `dataset-annotation/plan.md:100`; `backlog.md:96,111` | учить на чистом кадре; оверлей — только показ |
| O8 | Сохранение кадров: новый `dataset_capture` против расширения `frame_saver` | `dataset-annotation/phase-3-capture.md:18,38`, `context.md:14`; `backlog.md:87-89,102`; `dataset-circle-capture.md:28` | один писатель пар «кадр + `.json`» (решение владельца №8 — `.json` рядом, то же имя) |
| O6, O7 | Экспорт в `ml_train` и YOLO/COCO описаны в двух местах | `layer-render/plan.md:123-131,156-157`; `dataset-annotation/plan.md:54,166`, `phase-1-dataset-service.md:69`, `phase-4-quality-export.md:108,123` | один экспорт в `draw`/`labeling`, оба плана — потребители |
| O9 | `overlay_draw` правили четыре плана: вход `image/*`, побайтная копия кадра, необязательный `overlay` | `code-reader-gui.md:35,46,49`; `2026-10-18_camera-device-service/tasks/3.4.md:6,17,20`; `topology-port-join.md:9`; `dataset-circle-capture.md:29` | `draw-universal` сохраняет эти контракты — в приёмке задач. camera-device-service 3.4 ещё PENDING: правило копии кадра входит в draw-universal Task 1.1, а 3.4 убирает `overlay_draw/plugin.py` из своих FILES (`draw-universal/design.md` §4) |
| O11 | `word_layout` + `sidecar.track_id` / `frame_id` | `backlog.md:88,101`; `word-layout/tasks/C-32.md:1,17`; `letter-robot-cycle/plan.md:138,216` | свести при планировании DS-1 |
| O1–O5 | Синтетика: один веб-редактор в `pult_web` у двух планов, Qt `sim.*`, `line_sim/core/factory.py`, `letters_layered.yaml`, `dataset_gen` | `layer-render/phase-5-editor.md:21`, `plan.md:121`, `phase-2-core-2.4b.md:24`; `line-sim-layer-editor/phase-1-canvas-html.md:34`, `phase-1-qt.md:5`, `phase-1-engine.md:16,86` | решить при пересмотре `layer-render` |

## Порядок внутри группы (предложение, до решения владельца)

1. `draw-universal` Ф0–Ф3 (Ф4 по желанию) — путь показа, чистый кадр.
2. Параллельно, если хватает писателей: DS-1 — пары и раскладка в `frame_saver`, общий `ItemTemplate`.
3. Сведение `dataset-annotation` с `labeling` из CTO r2: одно решение по O6–O10, потом её Ф1.
4. Пересмотр `layer-render` вместе с `line-sim-layer-editor` (O1–O5; Ф7 шрифты, Ф9 регионы = фигуры `draw`, LR-001).
5. `letters-retrain` Ф1 — по готовности синтетики и экспорта.
