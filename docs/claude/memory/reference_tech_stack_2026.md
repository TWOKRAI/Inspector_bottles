---
name: tech-stack-2026
description: При любых улучшениях стека/перфа/зависимостей сверяться с docs/direction/TECH_STACK_2026.md — живой стратегический документ владельца
metadata: 
  node_type: memory
  type: reference
  originSessionId: 768c4056-8d38-4ee3-a3f1-d58bf502abff
---

`docs/direction/TECH_STACK_2026.md` — живая стратегия нативного стека (2026-07-12, владелец): что внедрять (msgspec, orjson, Polars, py3.13, ORT EP), что пилотировать (OpenCV 5, PySide6 6.11, PyO3, anomalib, Rerun), что отклонено (ROS 2 целиком) и триггеры наблюдения (Zenoh, iceoryx2, free-threading, Hailo).

**Why:** владелец явно попросил ссылаться на этот документ при предложениях улучшений — там уже приняты решения и зафиксированы волны.

**How to apply:** перед предложением новой зависимости/оптимизации/технологии — проверить её статус в TL;DR-таблице §0 и волнах §12; пересекающееся с hot-path исполнять в составе Ф7 (принцип «одним вскрытием», см. QUEUE «Параллельный трек — TECH_STACK»). Чистка pyproject (§11: 10 мёртвых core-deps) — первый шаг Волны 1. См. [[constructor-master: прогресс исполнения]].
