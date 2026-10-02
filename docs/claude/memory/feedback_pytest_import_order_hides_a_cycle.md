---
name: feedback_pytest_import_order_hides_a_cycle
description: "Зелёный pytest не доказывает отсутствие цикла импорта: conftest'ы и соседние тесты грузят пакеты раньше, цикл виден только в чистом процессе с нужным пакетом ПЕРВЫМ"
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

**Why:** неверная причина в отчёте инъекций переживает задачу (правило «объяснение без воспроизведения»); второй раз
подряд за день ревьюер опроверг моё объяснение расхождения прогноза.

**How to apply:** расхождение прогноза инъекции объяснять только после прогона, который это объяснение проверяет; для
импортов — чистый процесс в обоих порядках. Связано: [[feedback_one_control_proves_sufficiency_not_exclusivity]],
[[feedback_plausible_is_not_verified]], [[feedback_an_injection_must_prove_its_axis_is_live]].
