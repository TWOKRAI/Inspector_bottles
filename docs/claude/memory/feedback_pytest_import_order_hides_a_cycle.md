---
name: feedback_pytest_import_order_hides_a_cycle
description: "Зелёный pytest не доказывает отсутствие цикла импорта: conftest'ы и соседние тесты грузят пакеты раньше, цикл виден только в чистом процессе с нужным пакетом ПЕРВЫМ"
mechanism: "import-cycles"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 5bc31c13-6f2a-47b3-a889-0f5142a6cc4f
  modified: 2026-10-02T18:44:38.331Z
---

Отсутствие массового красного в pytest не доказывает, что цикла импорта нет. Conftest'ы и соседние тесты загружают
пакеты в своём порядке, и цикл, зависящий от порядка, молчит. Проверять в чистом процессе: `python -c "import A"` и
`python -c "import B"` по отдельности, каждый подозреваемый пакет первым.

Случай (layer-render Task 2.4a, 2026-10-02). Инъекция i5: `layer_render/catalog.py` берёт `procedural_background` из
`dataset_gen`. Я ждал массовый красный, получил 14 точечных и записал «цикла нет» с выдуманной причиной. Ревьюер
воспроизвёл: `import Services.layer_render` первым → `ImportError ... partially initialized module
'Services.layer_render.catalog'`; `import Services.dataset_gen` первым → ok. Сторожат такое только тесты-подпроцессы.

Второй случай (2.4b i11, 2026-10-03). Заплата `layer_render.factory` → `dataset_gen.core.augment` не дала `ImportError` ни в одном порядке, и я записал «цикла нет». Ревьюер: цикл пакетов есть (`factory → dataset_gen.core.augment → layer_render.effects`), молчит лишь потому, что `dataset_gen` импортирует из `layer_render` одни подмодули. **Отсутствие `ImportError` ≠ отсутствие цикла**: цикл ищут по рёбрам импорта (сканер границ, `sentrux`), а падение — его частный случай.

**Why:** неверная причина в отчёте инъекций переживает задачу (правило «объяснение без воспроизведения»); второй раз
подряд за день ревьюер опроверг моё объяснение расхождения прогноза.

**How to apply:** расхождение прогноза инъекции объяснять только после прогона, который это объяснение проверяет; для
импортов — чистый процесс в обоих порядках. Связано: [[feedback_one_control_proves_sufficiency_not_exclusivity]],
[[feedback_plausible_is_not_verified]], [[feedback_injection_zero_may_mean_the_guards_were_not_collected]].
