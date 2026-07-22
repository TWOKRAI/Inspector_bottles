---
name: router-errors-attribution
description: Как атрибутировать RouterManager.errors по точкам без патча + две слепые зоны наблюдаемости (мьютированный QueueRegistry, усечённый RouterStats)
metadata:
  type: project
---

`RouterManager.errors` атрибутируется по точкам **арифметикой, без патча и без DEBUG-логов**:

```
sent_attempted - middleware_dropped - sent_via_targets - sent_via_channel  ==  errors
```

Точное равенство ⇒ 100% ошибок в ветке «no channel resolved» (`_do_send`, router_manager.py:349).
Если бы вклад давали канальные точки (365/377), исключение (384), приём (949) или
`self._receiver.errors` (его добавляют к `_stats["errors"]` в `get_stats`, ~стр. 1248) —
`errors` был бы БОЛЬШЕ остатка. Перекрёстные подтверждения: `channels[*].send_errors`,
`channel_put_timeouts`, число строк `receive error` / `_do_send exception` в логах.

Причина за строкой 349 читается по `queue_system_evict_blocked`: рост 1:1 с `errors` ⇒
доставка упёрлась в ПОЛНУЮ never-drop (system) очередь, а не в «нерезолвленный канал»
(текст ошибки на 349 вводит в заблуждение). system-очередь = maxsize 100, QoS never-drop.

**Why:** заход 2026-07-21 встал на том, что причину пишут в `_log_debug`, а поднять
уровень через `config_reload` не вышло (ложный success). Арифметика обошла оба барьера.

**How to apply:** сырые счётчики брать из `driver.router_stats(p).raw["result"]["router_stats"]`.

## Две слепые зоны (проверено, не предположение)

1. **`QueueRegistry._log_error` не доходит НИ В ОДИН лог-файл.** Ни throttled ERROR
   «system-очередь переполнена» (`queues/core/manager.py`, ~346), ни `send_to_queue('X','system') failed`
   (~214) — 0 вхождений по всему `logs/` при десятках тысяч событий. Именно эта строка несёт
   ИМЯ процесса-получателя, поэтому цель потери не видна штатными средствами. Заявленное в
   докстринге «потеря становится ВИДИМОЙ» в этой сборке не выполняется.
2. **Типизированный `RouterStats` отдаёт только 4 поля** (`errors`/`sent_ok`/`received`/
   `middleware_dropped`) — без `sent_attempted`/`sent_via_*`, то есть атрибуцию через него
   сделать нельзя в принципе. Нужен `.raw`.

Смежное: [[project_state_gate_vs_fence_confusion]]
