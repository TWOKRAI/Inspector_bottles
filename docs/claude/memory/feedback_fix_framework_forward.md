---
name: feedback_fix_framework_forward
description: "Framework bugs — authorized to fix when blocking; changes must IMPROVE, not delete functionality (fix-forward, don't gut)"
metadata:
  node_type: memory
  type: feedback
  originSessionId: bb0fcd93-6055-4985-9294-c8457ff65f72
---

Владелец (2026-06-04): «если нужно починить баги во framework — делай. Главное что на улучшение, а не удаление».

**Why:** уточняет [[project_priority_product_over_engine]] — приоритет «продукт > движок» НЕ означает «не трогать движок». Framework-баги, блокирующие фичу, чинить разрешено и нужно. Граница — в *направлении* правки: улучшать/чинить-вперёд, а не решать проблему вырезанием рабочего (или задуманного) функционала.

**How to apply:**
- Наткнулся на латентный/реальный баг framework, мешающий задаче → чини, не обходи и не оставляй (даже если план говорил «без правок framework»).
- При выборе «оживить сломанный механизм правильным фиксом» vs «удалить мёртвый код» → по умолчанию **fix-forward** (пример: `_publish_state` плагинов оживили фиксом `with_config`/`merge`, а не погасили — см. [[project_telemetry_db_sink]]).
- Удаление функционала — только с явного согласия владельца, не как способ «закрыть» баг.
- Не путать с осторожностью к прод-эффектам: чинить — да, но прод-влияние (напр. GUI-телеметрия) всё равно проверять живьём (qt-mcp), см. [[feedback_qt_mcp_smoke_verification]].
