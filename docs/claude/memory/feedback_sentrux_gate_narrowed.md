---
name: feedback_sentrux_gate_narrowed
description: "Владелец сузил sentrux pre-push gate: блок только на quality↓/циклы↑/god↑; мягкие метрики (complex-fn/coupling/depth) → warning, не блок"
metadata:
  type: feedback
---

Владелец (2026-07-15) сузил sentrux structural pre-push gate — раньше он был all-or-nothing
(любая регрессия любой под-метрики → блок push).

**Теперь:**
- **Жёсткий блок push:** падение aggregate quality · рост циклов · рост god-файлов.
- **Мягкие метрики** (complex-fn / coupling / depth / hotspot) → **WARNING, НЕ блок**;
  фиксируются осознанно через `sentrux gate --save`.
- **Fail-closed:** если summary-метрики не распознаны (дрейф формата sentrux) → блок консервативно.

**Why:** гейт заблокировал push, где aggregate **quality ВЫРОС** (7089→7099), из-за +1
complex-function (H-ремедиация добавила нужную функцию безопасности). Ложная тренировка:
владелец ценит guardrail на реальные структурные регрессии, но не погоню за непрозрачным
числом под-метрики. Связано с [[feedback_sentrux_depth_opaque]] (метрики sentrux непрозрачны).

**How to apply:**
- Источник хука — `scripts/hooks/pre-push` (git-tracked; ставится `scripts/install_pre_push_hook.sh`).
  НЕ возвращать к all-or-nothing `if ! sentrux gate`.
- Если push «заблокирован» на мягкой метрике — теперь это warning, push пройдёт; при желании
  зафиксировать рост осознанно `sentrux gate --save` (обновит `.sentrux/baseline.json`).
- Реальная структурная регрессия (цикл/god-файл/quality↓) по-прежнему блокирует — это правильно.
