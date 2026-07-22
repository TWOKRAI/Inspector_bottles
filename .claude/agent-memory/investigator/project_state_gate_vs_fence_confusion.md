---
name: project-state-gate-vs-fence-confusion
description: Отказы state.merge с reason='middleware' — это TopologyGateMiddleware (ADR-SS-019), НЕ fence; драйвер под fence не попадает в принципе
metadata:
  type: project
---

Два РАЗНЫХ механизма постоянно путают, потому что оба «молча отбрасывают control-plane»:

1. **`TopologyGateMiddleware`** (state_store, ADR-SS-019, b1a6ef37) — отклоняет
   `state.set`/`state.merge` в `processes.<name>.*`, если `<name>` нет в топологии.
   Признак: ответ `{'status':'rejected','reason':'middleware'}`. Гейт НЕ пишет
   `context["rejection_reason"]`, поэтому всплывает generic-дефолт `"middleware"` —
   ни имени мидлвари, ни причины. Хук отказа логирует в `_log_debug` → на дефолтном
   уровне невидим.

2. **fence-фильтр** (message_module) — дропает `_fence`-штампованное от устаревшего
   incarnation. Признак: **ответа нет вообще** (таймаут) + WARNING `fence: отброшено...`.

**Why:** отличать по форме отказа. `rejected`-ответ = гейт/пайплайн state (сообщение
ДОШЛО до хендлера). Таймаут без ответа = дроп на receive-мидлвари.

**How to apply:** backend_ctl-драйвер под fence не попадает **в принципе** — в
`backend_ctl/*.py` ноль упоминаний `_fence`, а `make_fence_filter_middleware`
пропускает нештампованное прозрачно (fail-open). Гипотеза «драйвер не штампует fence →
inc=0 → дроп» неверна дважды: нештампованное ≠ inc=0. `inc=0` в живых логах — от
РЕАЛЬНЫХ процессов (напр. `camera_0` после бампа incarnation на switch).
Гейт при этом path-based, а не sender-based: драйвер свободно пишет в
`processes.<реальный>.*`, инструмент не покалечен. См. [[project-k8-topology-editor-kill]].
