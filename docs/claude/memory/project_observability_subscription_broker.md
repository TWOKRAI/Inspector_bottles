---
name: project-observability-subscription-broker
description: Брокер подписки 5.11 — намерение «хочу всё» у PM, переподписка на шве инкарнации; backend_ctl не мигрирован
metadata:
  type: project
---

Task 5.11 (`plans/observability-unified-routing.md`, 2026-07-29). Подписка на живой
хвост наблюдаемости больше не строится потребителем: PM держит реестр намерений
(`ObservabilitySubscriptionBroker`) и разворачивает их в `observability.tail.subscribe`
одним broadcast'ом. Записи по-прежнему идут адресным пушем НАПРЯМУЮ подписчику —
PM брокер, а не транзит.

**Где висит переподписка:** `_mark_instance_started(name)` — через неё проходят ВСЕ
пять путей старта (boot, `start_process`, `restart_process`, автостарт, пересоздание
топологией). Прежние триггеры потребителей (`supervisor.event="recovered"`) видели
только цикл supervisor'а и промахивались мимо ручного рестарта — это был резидуал F4
GUI-активатора, и он закрыт тем, что триггер стал не нужен.

**Форма взята у** `_replay_telemetry_runtime_delta` (PM хранит рантайм-намерение и
доигрывает пересозданным детям). Второй конструкции для той же задачи не заводилось.

Сделано: брокер + команды `observability.tail.subscribe_all`/`unsubscribe_all` +
readback (секция `broker` в `introspect.observability` через хук
`observability_introspect_extra`) + инвариант «процесс не подписывает себя на себя»
(живёт у процесса, не у вызывающего) + GUI-потребитель.
Попутно закрыты R4 (watcher раздаёт правку файла детям, [[project-observability-config-layers]])
и R6-E/F/G.

**Не сделано: миграция `backend_ctl`.** Это снос целого контура (applier-поток,
очередь намерений, дедуп, самоисцеление, `manifest`/`resume`) — ~60 ссылок в 8
тестовых файлах, 4 из них live. Отложено сознательно: сносить хардененный контур без
живого прогона — ровно [[feedback-tool-features-before-validation]].

Живой прогон 5.11 (switch + ручной рестарт парой до/после) — тоже остаток.
