---
name: project-backend-ctl-d1-session-isolation
description: "D.1a изоляция + D.1b-чтение (supervision.status) + §8 гейтинг курсоров ЗАКРЫТЫ (ветка feat/bctl-d1-session-isolation, ~11 коммитов): Вариант A in-band session + dotted-subscriber (router/push НЕ тронуты), флаг default OFF. Осталось: формальное ревью → merge → D.2. Follow-up: supervise-действия, per-event numeric epoch."
metadata:
  type: project
---

Мини-план `plans/backend-ctl-d1-session-isolation.md` (гейт Phase D родителя `backend-ctl-debug-console.md`). Развилка §5 делегирована владельцем на **рассуждение Fable** → **Вариант A**, верифицирован чтением.

**Механизм (переиспользуемо для D.2 и любых внешних socket-подписчиков):** в router УЖЕ есть иерархическая dotted-адресация (`message_module/addressing/address.py`, P0.2) + мост Ф1.1b (`router_manager.py:391-408`, `_deliver_by_targets`: `targets=["backend_ctl.<sid>"]` → `_address=[name,sid]` в билете → `channel_registry.get(name)` → `_deliver_via_channel`). Значит **per-session адресация push внешнему socket-каналу достигается БЕЗ правок router и трёх push-строителей** (delta_dispatcher / record_forward / router_push) — только через dotted-subscriber на клиенте. Reply адресуется in-band полем `session`; резолвит **только канал**.

**Что сделано (D.1a):**
- `SocketChannel(session_isolation=False)`: `_sessions {sid:sock}` под `_clients_lock`; `send()` резолвит sid из `session` (reply) или `_address[1]` (push) → один сокет; unknown sid → **error, НЕ broadcast**; без sid → broadcast (back-compat); bind в `_handle_line`, unbind в `_drop_clients` (по 1 точке); `get_info` += `sessions`/`session_isolation`.
- `SocketBridgeAdapter(session_isolation=False)`: `msg.pop("session")` **ВСЕГДА** до `router.request` (не течёт в handler'ы); эхо `session` в response только при ON.
- `backend_ctl_endpoint`: `_resolve_session_isolation` (config `backend_ctl.session_isolation` OR env `BACKEND_CTL_SESSION_ISOLATION=1`, **default OFF**), проброс параметром конструктора в канал+адаптер.
- Клиент (`transport.connect`): `_session=uuid4().hex[:12]` per-connect + `_subscriber="<sender>.<sid>"`; `_send_raw` инъектит `session` в каждое сообщение (единственный choke-point); `_sender` НЕ тронут. Дефолт subscriber во всех subscribe/tail/watch/untail → `_subscriber` (7 мест). `replay_subscriptions` пере-нацеливает свой durable-subscriber на текущую сессию (`_retarget_subscriber`) — реконнект под новым sid не бьёт push.
- Acceptance `test_session_isolation.py` (integration, не live): два driver'а изолированы (reply/push/ghost + distinct subscribers). Бонус: dotted-subscriber чинит коллизию — раньше `log_untail` одного driver'а снёс бы хвост обоих под общим `"backend_ctl"`.

sentrux Δ0 (7008→7008, циклов +0, 0 нарушений). Регресс — только pre-existing env (2 live-теста observability + порт-8765 конфликт от подвисшего бэкенда, воспроизводятся и на базе).

**D.1b + §8 (ЗАКРЫТЫ 2026-07-19):** команда `supervision.status` (PM: epoch + per-process incarnation/restart_count/last_exit/status; monitor `get_supervision_snapshot`) + driver `supervision_status` + MCP tool (SAFETY_READ). §8 — EventHub ротирует generation-токен на supervisor-границе рестарта (`processes.<name>.supervisor.event` ∈ {recovered,crashed,gave_up}) → курсор «до рестарта» даёт `reset_required` (закрыт долг B.1 «чтение сквозь границу инкарнации»), driver-side, без правок server push-путей. Консервативно (safe superset).

**Отложено (follow-up, НЕ acceptance):** `supervise(action=restart|drain_restart|set_policy)` — `restart` уже есть (`process.restart`), drain/live-policy = новая machinery; численный epoch/incarnation в КАЖДОМ событии (плумбинг shared push-путей, которых D.1a избегал); регенерация `CAPABILITIES.yaml` (новая команда) на рабочем харнессе — в текущем env харнесс сломан (introspect-хендлеры не регистрируются, `_live`/`harness_smoke` тесты красные, дамп вырождается). `test_hard_kill::test_already_dead_is_not_error` — pre-existing (harness.py не менялся).

**Осталось по D.1:** формальное `/code-review` → merge → **разблокирует D.2** (streamable-HTTP мультиклиент). Осиротевшие durable-подписки мёртвой сессии — out-of-scope, вход D.2.

Layer для коммитов backend_ctl — `mixed` (см. [[feedback-backend-ctl-layer-mixed]]). Тестировать бэкенд через driver, не qt-mcp ([[feedback-backend-ctl-for-agents]]).
