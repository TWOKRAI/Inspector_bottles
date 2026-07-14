---
name: f7-g4-done
description: "Ф7 G.4 (QoS-профили + per-camera кольца SHM + чистая замена wire на switch) ЗАКРЫТ 2026-07-14 merge e6b1bcca; Вариант A — владение слотами (refcount/release/reclaim) перенесено в G.5; всё за FW_QOS_PROFILES default-off"
metadata:
  node_type: memory
  type: project
---

Ф7 G.4 — **ЗАКРЫТ 2026-07-14, merge `e6b1bcca` (--no-ff) в main** (ветка `feat/constructor-f7`).
Правда исполнения — [`plans/2026-07-06_constructor-master/g4-execution-plan.md`](../../../plans/2026-07-06_constructor-master/g4-execution-plan.md).

**Развилка скоупа (решение владельца простым языком, 2026-07-14): Вариант A — «механику владения
подносом делаем вместе с G.5».** Причина: путь кадра сегодня **copy-out** (читатель `.copy()`-ит,
слот сразу свободен) → настоящее «владение слотом до release последним читателем» нагружено только
с zero-copy (G.5); в CPython **нет cross-process atomic RMW** на байте header'а → fan-out refcount
потребовал бы лока на hot-path, а глубокое кольцо+seqlock дают ту же безопасность БЕЗ atomic.

**Что приземлилось (3 под-шага, всё за `FW_QOS_PROFILES` default-off, откат бит-в-бит, flip на G.7):**
- **G.4.a** (529e8ab6): `shared_resources_module/qos.py` — `QoSProfile{reliability,history_depth,
  drop_policy,deadline_ms}` (frozen, инвариант reliable⟺never) + `QOS_PROFILES` (ключи kind==queue_type)
  = единый источник never-drop под 3 поверхности переполнения (минус 2 хардкода). Data-дроп из
  очереди стал ВИДИМЫМ: `data_evicted`/`system_evict_blocked` (всегда-on) → `RouterManager.get_stats`
  → heartbeat → `state.shm.*`. ADR-SRM-012.
- **G.4.b** (91337e1b): глубина кольца SHM настраивается per-camera (`buffer_slots` wire / `frame_ring_depth`
  конфиг → `FrameShmMiddleware._resolve_ring_depth`), раньше жёстко 3 и buffer_slots игнорировался (B-8).
  N owner = N изолированных колец (keying по имени процесса-источника — любой источник).
- **G.4.d** (ee98925e): чистая замена wire на re-issue — `_teardown_wire_middleware` снимает старый
  middleware с router'а ДО нового (раньше молча перезаписывал → **утечка middleware + двойная
  обработка + стейл handle-cache**). Это безопасный refresh handles на switch (B-7). Кросс-процессный
  дренаж живой очереди получателя ОТВЕРГНУТ владельцем как костыль (ронял бы валидные кадры); стейл-
  тикеты → точечный read-time drop по incarnation (G.3, уже есть).

**Гейт:** 4582 passed / 6 skipped / **2 pre-existing app_module Windows-fail** (см. [[app-module-windows-test-debt]],
вне скоупа), sentrux 9/9, quality 7093→7094, 0 циклов. **Ревью:** 3 Sonnet-финдера (6 находок закрыты
review-fix 70d73715 — главное: гейт глубины за флагом = откат бит-в-бит; честные доки про несуществующий
«счётчик на wrap кольца») + **Fable APPROVE-WITH-NITS** (фокус владельца «что универсальнее для
конструктора»: 100% diff в движке, ноль строк в prototype/Services/Plugins, DDS/iceoryx2-совместимый
контракт; 5 нитов → G.5/G.7).

**НЕ улучшилось / долги (ниты Fable → G.5/G.7):** (1) BoundedChannel к профилю не подключён («3
поверхности» = 2 wired + 1 documented); (2) нет extension-point прикладных kind в QOS_PROFILES; (3) два
имени ручки `buffer_slots`/`frame_ring_depth`; (4) `queue_*`-счётчики под именем `state.shm.*`; (5)
`deadline_ms` инертен. **Чек-лист G.7-флипа:** soak со сдвигом глубины wire-колец 3→4 (следствие
pre-Ф7 дефолта buffer_slots=4).

**Следующее — G.5** (снятие двойной конверсии + zero-copy `restore_frame(copy=False)`), Sonnet по
[[model-economy-scheme]]. **Именно в G.5 приземляется протокол владения слотами** (free-list + release
последним читателем + fan-out refcount + reclaim-on-death + kill-9 fault-injection) — там zero-copy
делает его нагруженным и осмысленно тестируемым, header G.3 (state/refcount) уже готов. Урок сессии:
Вариант A = fewer-layers по существу (не строить самый сложный протокол вслепую без потребителя).
Продолжает [[f7-g3-handoff]].
