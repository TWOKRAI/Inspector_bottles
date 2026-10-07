---
name: feedback_elements_from_point_misses_pseudo_elements
description: "Артефакт на стенде страницы (browser stand) списан на курсор: elementsFromPoint вернул BODY, а рисовал псевдоэлемент ::details-content закрытого details — ответ «элемента нет» не опровергает артефакт"
mechanism: [live-stand, probes]
metadata:
  node_type: memory
  type: feedback
---

2026-10-05, plans-progress Task 7.1, живой стенд в Chrome. Под кнопкой «Планы ▾» на снимке
была горизонтальная полоса. Проверил `document.elementsFromPoint(100, y)` → `BODY > HTML` и
решил: «не элемент страницы, курсор». Ревью кода (headless Chrome `--screenshot`) нашло дефект
major: закрытый `<details class="switcher">` рисует рамку, фон и тень своего `::details-content`
(у закрытого он `content-visibility:hidden` — содержимое скрыто, бокс нет), а открытый список
уходит за левый край.

**Why:** `elementsFromPoint` возвращает только элементы, псевдоэлементы (`::before`, `::after`,
`::details-content`, `::marker`) в выдачу не попадают. «В точке нет элемента» — не доказательство
того, что артефакт не от страницы. Тот же класс, что [[feedback_plausible_is_not_verified]]:
удобное объяснение приняли без парной проверки.

**How to apply:** артефакт на снимке стенда — дефект, пока не доказано обратное: снять тот же
кадр без курсора (zoom области, другая позиция мыши) и проверить псевдоэлементы —
`getComputedStyle(el, '::details-content')` у ближайших `<details>`, `::before`/`::after` у соседей.
Свёрнутые элементы на стенде проверять в обоих состояниях (закрыт / открыт) и на 2–3 ширинах.
