# Plugins/sim/layer_preview — STATUS

**Состояние: сделано (редактор слоёв Task 1.2a, ревью S1 — превью вынесено из `scene_source`).**

**Обновлено:** 2026-09-29, ветка `feat/line-sim-layer-editor` — Task 1.3h-a, команда `preset.layout`.

| Что | Состояние |
|---|---|
| `LayerPreviewPlugin`, команда `preset.preview` | есть; P6/P7 приёмки тестера 1.2a перенесены сюда без ослабления |
| Процесс `layers` в `apps/line_sim/pipeline.yaml` | есть; живой стенд `LINE_SIM_LIVE=1` — 32 passed, 5 процессов (с каталогом классов) |
| Перечитывание файла по `rev` | есть (тест: превью видит commit через `scene_source`) |
| Ограда путей, лимиты, бюджет пикселей | есть |
| `preset.preview` на живом стенде через роутер | **не проверено** — стенд поднимался, команда в `layers` не вызывалась |
| HTTP-маршрут в `pult_web` | есть — `/api/preset/preview` (1.2h), `/api/preset/layout` (1.3h-a) |
| Команда `preset.layout` (1.3h-a) | есть: 9 приёмочных тестера вслепую + 3 авторских hazard; инъекции лида I1–I12 — 10 свойств охраняются, пробелы: defect-слои в раскладке и `seed=True` (I9, I10) |
| `preset.layout` на живом стенде через роутер | **не проверено** |
