---
name: Pipeline demo recipe and telemetry state
description: Демо-рецепт webcam→split→processing→merge→display + wire telemetry Phase 7b
type: project
---

Phase 7a/7b: PipelineTab на нативном QGraphicsScene получил полный набор узлов, телеметрию wire'ов и демо-рецепт.

**Phase 7a** (коммит `935c2b49`):
- `DisplayNodeItem` — узел Display первого класса в QGraphicsScene (input port)
- `target_process` binding — узел привязывается к процессу из рецепта
- graph↔blueprint сериализация (двусторонняя)

**Phase 7b** (коммит `4a3b0b28`):
- `WireStatus` телеметрия: `Literal["idle","active","error"]` + overlay на wire'ах
- `blur` плагин в `Plugins/processing/blur/` (~50 строк, OpenCV GaussianBlur)
- `clear_all()` эмиттит `edge_removed` для корректной очистки телеметрии
- Demo-рецепт `demo_webcam_split_merge.yaml`: webcam→split→(gray+blur / color_mask+negative)→merge→display

## Связанные ADR / коммиты
- Phase 7a DONE: коммит `935c2b49`
- Phase 7b DONE: коммит `4a3b0b28`; fix: `clear_all` + строгий Literal для WireStatus.state
- Demo-рецепт: коммит `da227903` (кнопка запуска) + `da227903` (рецепт e2e)

## Ключевые пути
- `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml` — демо-рецепт
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/` — PipelineTab, WireStatus, DisplayNodeItem
- `Plugins/processing/blur/` — blur-плагин

## Статус
Phase 7b DONE (2026-05-27). Stable. Демо-рецепт загружается и запускается через «Запустить активный рецепт».
