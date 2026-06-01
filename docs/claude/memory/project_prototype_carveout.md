---
name: project-prototype-carveout
description: Carve-out универсальных частей прототипа → framework; пилот SystemBuilder; domain/adapters отложены
metadata:
  type: project
---

Направление (решено в сессии, исполнение — в новом чате): выносить универсальные части
`multiprocess_prototype/` во `multiprocess_framework/` как модули. Подход — carve-out как
**forcing function** (перенос заставляет сделать interfaces.py + split + контракт-тесты).
Прецедент: Phase 4 (sql→Services), Phase 5 (Plugins).

Baseline sentrux прототипа: quality 7065, ацикличность 10000 (0 циклов), узкое место —
модулярность 4377, покрытие ~49%. frontend 341 файл (app-specific, остаётся).

**Честные рамки:** (1) выносимая поверхность узкая — тяжёлое generic уже вынесено; (2)
domain/adapters (~14k loc) — ловушка одного потребителя, НЕ трогать пока нет 2-го приложения;
(3) characterization-тесты пишутся ДО переноса (49% покрытия); (4) god-файлы (presenter.py
~1700, inspector_panel.py ~870) carve-out закрывает частично — split app-side отдельно.

План: `plans/prototype-carveout.md`. Этап 0 — аудит-карта (universal/app-specific/coupled +
обратные импорты). Этап 1 — пилот вынос SystemBuilder (backend/launch.py, шов уже помечен) с
session_start→end замером. Этап 2 — решение по graph-editor/примитивам по результату пилота.

**Why:** владелец хочет навести порядок и сделать фреймворк реально переиспользуемым; идёт против приоритета продукт>движок ([[project-priority-product-over-engine]]) — решать осознанно.
**How to apply:** в новом чате начать с Этапа 0 (investigator-аудит), не с big-bang; пилот мерить sentrux-дельтой.
