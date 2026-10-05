---
name: observability-tail-repair
description: "Хвост-ремонт Т-1…Т-5 ЗАКРЫТ 2026-08-12: гейт 6855×3, fw 7814×3, Н3-1 закрыт ADR-PMM-027 — вход в этап 6 открыт"
metadata:
  node_type: memory
  type: project
  originSessionId: e261020d-c8af-43b5-9e51-f1aa2099dd0d
  modified: 2026-08-12T16:54:27.624Z
---

Ремонт хвоста по жёсткому ревью 2026-08-12 (`docs/reviews/2026-08-12_observability-hard-review.md`)
**закрыт целиком, все пять задач Т-1…Т-5**. Вход в этап 6 (телеметрия) открыт; порядок дальше —
этап 6 → этап 8, этап 7 параллельно.

Числа приёмки: корневой гейт **6855 passed / 0 failed / 64 skipped ×3 подряд**; фреймворковая сьюта
**7814 passed / 0 failed ×3** (флейк HR-4 вылечен честным дедлайном 6 с → 60 с, не карантином);
сверщик документов 14/0 расхождений; `validate.py` чист.

**Н3-1 закрыт (ADR-PMM-027).** Корень — не гонка: `on_session_closed` вёл в
`_forget_observability_session`, чистивший ОДНУ плоскость, а призрака давала соседняя — подписка
`state.**` мёртвого адреса. Добавлен `StateStoreManager.forget_session`, колбэк переименован в
`_forget_closed_session` и обходит плоскости независимо. Зонд `probe_n3_1_ghost_rst.py` зелёный на
двух стендах (рост 0); красная пара снята **живьём на том же HEAD** — со снятым обходом
state-плоскости +1032 отказа за 30 с. Новая пара штатных форм — `probe_t2_normal_forms_pair.py`.
Residual: подписки, взятые клиентом НАПРЯМУЮ у ребёнка (`log.tail`, прицельный `observability.tail`,
`ui.tap`), оркестратору неизвестны — вход этапа 8.

Форма (не поведение) — план-спутник plans/observability-dx.md = этап 10 roadmap: А ServiceContext
(делать вместе с 6.2!), Б двери конфига (Б.1 — требование к спеке 6.1: не пятая дверь), В
readback-протокол, Г карта потребления (основное даёт этап 6, после гейта поднять 9.1), Д дисциплина.
Резидуалы: `inspection_results.db`/`telemetry.db` без vacuum (этап 8), Н5-1/Н3-2 — входы спеки 6.1.
Открыто и НЕ чинилось (этап 8): две несогласованные реализации slug'а якорей — `scripts/link_check`
схлопывает серию пробелов, GitHub нет; правка одного link_check даёт −28/+53 битых.

Связано: [[gate-signature-lives-on-a-head]], [[cleanup-must-survive-abnormal-disconnect]],
[[qt-mcp-flag-value-is-compared-verbatim]].
