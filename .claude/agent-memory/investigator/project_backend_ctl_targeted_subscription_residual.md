---
name: backend-ctl-targeted-subscription-residual
description: Task 5.11 (observability_broker.py) закрыл ghost-подписки HR-2 ТОЛЬКО для оптовых (watch_like_gui/subscribe_all) намерений и state.**; прицельные observability_tail(process)/log_tail(process)/ui_tap(process) по-прежнему сиротеют при аварийной смерти клиента — остаток назван в коде самим проектом, не закрыт
metadata:
  type: project
---

**Факт, подтверждено HEAD d37735c6 (2026-08-28).** HR-2 (жёсткое ревью 2026-08-12) нашёл: TCP RST
посреди потока пушей → `errors_delivery_failed` у ProcessManager 0→1486 за 30с (~39/с) при НУЛЕ
живых клиентов — ghost-подписка `state.**` мёртвого адреса пушится вечно до рестарта бэкенда.

**Чем закрыто.** `ObservabilitySubscriptionBroker` (Task 5.11,
`multiprocess_framework/modules/process_manager_module/process/observability_broker.py`) держит
реестр ТОЛЬКО оптовых намерений (`subscribe_all`/`watch_like_gui`, маркер `scope="all"` —
`_fan_out` docstring, строки 262-263: «брокер держит ТОЛЬКО оптовые намерения»).
`ProcessManagerProcess._forget_closed_session` (process_manager_process.py:2782-2816) вызывается
из `SocketChannel(on_session_closed=...)` (проводка — process_manager_process.py:282; сам колбэк
дёргается из `_drop_clients` — socket_channel.py:362-382, единственная точка unbind, срабатывает
и на штатном FIN, и на RST/обрыве recv) — чистит ОБЕ плоскости: `_observability_broker.forget_session`
(оптовые obs-намерения) И `_state_store_manager.forget_session` (`state.**`). Это закрывает
HR-2 полностью для сценария из ревью (state.** через watch_like_gui).

**Что НЕ закрыто — назван самим кодом, не моя находка.** Docstring `_forget_closed_session`
(строки 2800-2804) дословно: «Residual (назван, не закрыт): подписки, взятые клиентом НАПРЯМУЮ у
ребёнка (log.tail.subscribe, прицельный observability.tail.subscribe, ui.tap.subscribe),
оркестратору неизвестны — реестра таких адресов у него нет... При аварийной смерти клиента они
остаются; штатное закрытие драйвера их снимает само.»

Подтверждено по `driver.py`: `observability_tail(process)` (1517-1557) и `log_tail(process)`
(1475-1493) шлют `observability.tail.subscribe`/`log.tail.subscribe` НАПРЯМУЮ процессу через
`send_command`, регистрируя намерение только в КЛИЕНТСКОМ `_SubscriptionRegistry`
(`subscriptions.py`, для реконнект-replay), НЕ в серверном брокере. Отдельный метод
`observability_tail_all()` (1579-1620, другая команда `observability.tail.subscribe_all`) —
единственный путь, попадающий под защиту брокера; это то, что вызывает `watch_like_gui()`.

**Why:** практическое следствие — если агент зовёт `observability_tail("preprocessor")` точечно
(не `watch_like_gui()`) и его MCP-сервер/сессия умирает аварийно (креш процесса, не graceful
close), форвардер на «preprocessor» продолжает пушить мёртвому адресу до рестарта ЭТОГО
процесса. Масштаб меньше HR-2 (один процесс, не вся топология через state.**), но класс дефекта
тот же и путь к нему открыт.

**How to apply:** при работе с этим модулем дальше — расширить `ObservabilitySubscriptionBroker`
(или завести аналог) до прицельных подписок, ЛИБО завести отдельный серверный реестр
`{session_id: [(process, command, args)]}` для НЕ-оптовых намерений с тем же `forget_session`-крюком.
Пока не сделано — рекомендовать агентам предпочитать `watch_like_gui()` точечным
`observability_tail`/`log_tail`/`ui_tap` там, где нужна устойчивость к креша сессии.
