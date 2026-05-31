# Этап 2 — Реактивный hot-apply процессов (средний)

**Цель этапа:** изменения топологии в редакторе (add/remove ноды) применяются к живому
бэкенду **реактивно** (без ручного «Перезапустить») — нода добавлена → процесс стартует,
нода удалена → процесс останавливается. Оживить `apply_topology_diff`
(`bridge/topology_bridge.py:497`), который был на legacy ActionBus и отключён при G.4.2,
переведя его на актуальное событие `TopologyReplaced` и proxy из Этапа 1.

**Сложность этапа:** Middle+ / Senior · **Риск:** средний
(консистентность, конфликт с ручными кнопками Этапа 1).
**Что переиспользуется:** `apply_topology_diff` (topology_bridge:497), proxy + методы
`start/stop_process` из Этапа 1, событие `TopologyReplaced` (domain EventBus, Phase B/E).
**Что пишется заново:** проводка события→diff→proxy, политика авто/ручного применения.

---

### Task 2.1 — Оживить apply_topology_diff на событие TopologyReplaced

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** при событии `TopologyReplaced` вычисляется diff (added/removed ноды/процессы)
и применяется через proxy: новые процессы стартуют (`start_process`), удалённые
останавливаются (`stop_process`) — без полного `replace_blueprint`, где это возможно.

**Context:** `apply_topology_diff` (`topology_bridge.py:497`) уже умеет считать diff, но
висел на legacy ActionBus (мёртв в проде — см. command-engine audit) и был отключён при
G.4.2. Domain-dispatch — единственный живой путь (EventBus, Phase B/E). В `app.py:462-464`
уже есть подписка `TopologyReplaced → topology_bridge.on_topology_changed()` (пока только
сброс IPC-кэша) — её и расширить: вычислить diff и направить в proxy из Этапа 1.
**Важно:** учесть порядок подписчиков (app.py:469-473 — TopologyReplaced приходит ПЕРЕД
PluginConfigChanged; не переставлять).

**Files:**
- `multiprocess_prototype/frontend/bridge/topology_bridge.py` (~497 `apply_topology_diff`) —
  убрать привязку к ActionBus, перевести на вызов через proxy
- `multiprocess_prototype/frontend/app.py` (~462-464 — уже есть
  `event_bus.subscribe(TopologyReplaced, lambda _e: topology_bridge.on_topology_changed())`,
  сейчас только инвалидирует IPC-кэш) — расширить обработчик на вычисление+применение diff
  через EventBus (НЕ ActionBus)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` — эмиссия
  `TopologyReplaced` при изменении графа (если ещё не эмитится при add/remove ноды)

**Steps:**
1. Найти, кто и когда эмитит `TopologyReplaced` (domain events, Phase B — 14 events).
   Убедиться, что add/remove ноды в редакторе приводят к этому событию (или добавить эмиссию).
2. Подписать `topology_bridge` на `TopologyReplaced` через живой EventBus/QtEventBus
   (НЕ ActionBus).
3. Внутри `apply_topology_diff`: для added → `proxy.start_process`, для removed →
   `proxy.stop_process`; для изменённых параметров — оставить готовый
   `SetPluginConfig`-путь (не дублировать).
4. Гарантировать idempotency и dict-границу.

**Acceptance criteria:**
- [ ] qt-mcp smoke: удалил ноду в редакторе (без нажатия «Перезапустить») → соответствующий
      процесс/эффект **пропадает на дисплее** реактивно (qt_snapshot до/после)
- [ ] Добавил ноду → процесс стартует реактивно
- [ ] Применение идёт через proxy/IPC dict; ActionBus не используется
- [ ] `python scripts/run_framework_tests.py` зелёный; нет дублирования с SetPluginConfig-путём

**Out of scope:** per-worker/адресное удаление (Этап 3); полная пересборка через replace_blueprint
(остаётся для кнопки/несовместимых diff).
**Edge cases:** diff содержит и add, и remove одновременно (порядок применения);
быстрые повторные правки (debounce/коалесцирование — продумать); diff, который проще
применить полным replace_blueprint, чем по частям (fallback).
**Dependencies:** Этап 1 (Task 1.1 — proxy), желательно Task 1.2.
**Module contract:** impl-only

---

### Task 2.2 — Политика авто-apply vs ручное (режим/флаг)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** teamlead
**Goal:** определить и реализовать политику, когда изменения применяются автоматически
(hot-apply Этапа 2), а когда только по кнопке (Этап 1) — чтобы авто-apply не конфликтовал
с ручным управлением и не вызывал неожиданных перезапусков во время редактирования.

**Context:** Без политики авто-apply будет дёргать процессы на каждое промежуточное
действие редактора и конфликтовать с ручными кнопками Этапа 1. Нужен явный режим
(например, тумблер «Live-режим» в тулбаре Pipeline) и/или коммит-точка (apply при
завершении редактирования ноды, не на каждое микро-изменение).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` — тумблер «Live-режим»
  (вкл/выкл авто-apply) в тулбаре
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` — флаг режима,
  гейтинг эмиссии/обработки `TopologyReplaced`
- `multiprocess_prototype/frontend/bridge/topology_bridge.py` — учёт флага перед применением diff

**Steps:**
1. Решить модель: (а) явный тумблер Live on/off; (б) apply по commit-точке (drop ноды /
   подтверждение), не на drag. Рекомендация: оба — тумблер + коалесцирование до commit.
2. Реализовать флаг в presenter; при выключенном Live кнопки Этапа 1 — единственный путь.
3. Защита от конфликта: пока выполняется ручной `replace_blueprint`, авто-apply подавлен.
4. Сохранять состояние тумблера (через ConfigStore, Phase D — не изобретать).

**Acceptance criteria:**
- [ ] Тумблер «Live-режим» виден и переключается; состояние сохраняется между запусками
- [ ] Live OFF: правки графа НЕ трогают бэкенд до нажатия кнопки (Этап 1)
- [ ] Live ON: правки применяются реактивно (Этап 2), без гонок с ручными кнопками
- [ ] qt-mcp smoke: проверить оба режима (qt_snapshot)
- [ ] Нет регрессий тестов

**Out of scope:** адресное granular-управление (Этап 3).
**Edge cases:** переключение Live ON при уже расходящемся графе vs runtime (синхронизация
при включении — применить разово); конфликт «ручная кнопка + Live ON».
**Dependencies:** Task 2.1
**Module contract:** impl-only
