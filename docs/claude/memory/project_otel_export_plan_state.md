---
name: otel-export-plan-state
description: Состояние плана otel-export (ред. 4, 2026-09-05) — форма «SDK в Services + плагин в GenericProcessApp + фрагмент топологии», база ветки closure, что сделано, ключевые ограничения
metadata:
  type: project
---

**Ред. 4 от 2026-09-05** (ревью `docs/reviews/2026-09-05_otel-export-plan-review.md`). Сделано: Task 0.1 (стенд `otelcol` 0.158.0 на `127.0.0.1:4318`, `tools/otel_stand/`), Task 0.2 шаг 1 (extras `[otel]`, пин 1.44). Остальное не начато.

Ключевые решения ред. 4:
- **База ветки — `feat/observability-closure` ≥ `46e970ab`**; старая `feat/otel-export` (один коммит) целиком её предок. Порядок слияния otel → closure → main.
- **Форма:** `Services/otel_export` (SDK без процесса) + `Plugins/io/otel_export` (плагин-хост в `GenericProcessApp`) + `backend/topology/otel_export.yaml` (фрагмент по образцу `observability_sink.yaml`). В `Services/` нет ни одного подкласса `ProcessModule` — стандартная форма side-effect-процесса именно плагин + фрагмент.
- **Дверь конфига — регистры плагина**, не `observability.otel_export`: с closure Task 2.2 незнакомый ключ секции на L3 отвергается, на файловых слоях — голос «ВНЕ КОНТРАКТА».
- **Числовая плоскость — два рода** (`stats`, `observation`), обе едут батч-форвардером без фильтра по уровню; v1 не экспортирует ни один.
- **Петля Р-3** закрыта стражем фреймворка (`subscribe_observability_tail` отказывает подписке на себя, `process_module.py:1240`) — свой фильтр только если петля предъявлена красной.
- **Task 2.4 (буфер/flush) — после closure Task 3.3**, той же формой предохранителя.
- **Карта пересечений с closure (по задачам, не по фазам):** 3.4→2.1 (сигнатура `declare_metric`), 4.3→3.4 (форма readback), 4.4→2.5 (форвардеры-сироты — чинит closure, здесь только ссылка), 4.5→0.4 (минимальный `ObservabilityPort` Protocol вместо своего контекста), 4.6 (экспортёр — НЕ логгер-sink через `register_sink_factory`), 5.1→4.3 (стражи docs_verify). Closure 5.4 принимает гейт Ф6 «без OTel-части» — зависимости нет. Ф3 closure на 2026-09-05 по коммитам: 3 из 9 (3.0, 3.5, 3.1).
- Находка универсальности: `service.instance.id = incarnation` не различает устройства — обязателен `host.name` в Resource (Task 1.2).

**Why:** план ред. 3 (2026-08-11) устарел за месяц по четырём посылкам; переработан целиком, чтобы Ф0–Ф1 можно было начать параллельно Ф3 closure.
**How to apply:** при старте любой задачи otel читать ред. 4, не память о ред. 3; Ф2–Ф4 чередовать со стендами closure (один порт 8765). См. [[project_observability_closure_progress]].
