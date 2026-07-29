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

**Живой прогон 5.11 закрыт 2026-07-29 — и нашёл дефект, которого не видели ни 6247
зелёных тестов, ни ревью.** Раздача со шва приезжала свежей инкарнации РАНЬШЕ, чем та
регистрирует команды (`run()`), — ребёнок писал `No handler for key
'observability.tail.subscribe'` и молча ронял её. После switch хвост шёл только от
пережившего `devices`, после ручного рестарта — ноль. Корень оказался шире брокера:
`ready_event` означал «инициализирован», а читался как «умеет принимать команды»
(см. [[feedback-ready-signal-meant-less-than-read]]). Теперь готовность объявляет сам
процесс в конце `run()`, а шов раздаёт за readiness-гейтом (daemon-поток, дедлайн
`observability_replay_ready_timeout_s`=30с, по истечении раздаём всё равно + WARNING).
Резидуал 5.11-R4: та же гонка живёт на `routing.refresh` и `config.reload`, у них
просто есть компенсация.
