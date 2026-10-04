---
name: project_telemetry_publish_control
description: "telemetry-publish-control ЗАКРЫТ (Фазы 0-4, ADR-PM-018): управляемая публикация телеметрии — errors always-on, logs/stats/telemetry вкл/выкл+частота у источника (publisher-gate в heartbeat), central-throttle как IPC-страховка"
metadata:
  type: project
---

**План `plans/telemetry-publish-control.md` ЗАКРЫТ** (ветка `feat/telemetry-publish-control`,
Фазы 0-4; ADR **ADR-PM-018** в `multiprocess_framework/modules/process_module/DECISIONS.md`).
Продолжение [[project_gui_telemetry_read_model]] — тот сделал дешёвое GUI-чтение, этот план — про
управляемую **запись/публикацию** телеметрии.

**Диагноз (Context плана):** (1) старый per-путь троттл (`build_throttle_rules`) был de-facto no-op
на телеметрию — `ThrottleMiddleware.before_merge` не переопределён, а телеметрия едет `proxy.merge`
(heartbeat self-publish), не `before_set`; (2) телеметрия НЕ идёт через `StatsManager` — у него нет
remote-транспорта в StateStore (см. [[project_telemetry_self_publish]]); (3) «управлять через stats
manager» = разместить ПЛОСКОСТЬ УПРАВЛЕНИЯ в stats/observability-конфиге, а данные оставить на
heartbeat-канале — не дублировать канал доставки.

**Принцип (ADR-PM-018):** «ошибки — всегда (always-on); логи/статистика/телеметрия — управляемо
(вкл/выкл + частота), декларативно из конфига, у ИСТОЧНИКА (publisher-gate в heartbeat), меняемо в
рантайме». Framework-first: контракт `TelemetryPublishConfig`, publisher-gate (`TelemetryGate`),
рантайм-команды (`config.reload`/backend_ctl `telemetry.*`), fan-out — во фреймворке; прототип задаёт
только значения (system.yaml/рецепт) + GUI-контролы (Task 4.1, шаблонная секция по `GATED_METRICS`).

**Две плоскости троттла:** publisher-gate (per-process, ГЛАВНЫЙ рычаг) + центральный
`ThrottleMiddleware` оркестратора (IPC-предохранитель, вторая линия) — см. ADR-PM-016 (тик
`publish.tick_sec`, heartbeat-liveness отделён от частоты телеметрии) и ADR-PM-017 (central-троттл
понижен до чистой страховки, дефолт 0.05с заведомо мягче publisher-дефолта; `capped_by_throttle` —
«no silent caps» видимость вместо тихого среза; Amendment Task 1.4 закрыл адресный per-process путь
через перехват в ProcessManager).

**Известный residual (сознательно не закрыт, задокументирован в ADR-PM-018):** две плоскости троттла
с равными дефолтами могут каскадировать — central-правило способно молча отменить попытку ПОДНЯТЬ
частоту через publisher при ручной строгой настройке (дефолтный сценарий уже смягчён ADR-PM-017).
Мера — видимость (`capped_by_throttle` до backend_ctl/GUI), не автоматическое разрешение конфликта.
Направление фикса на будущее: при активном publisher-gate на метрику ослаблять/снимать
соответствующее central-правило для НЕЁ.

Связано: [[project_observability_control_plane]], [[project_telemetry_self_publish]],
[[project_telemetry_coherence_remediation]], [[project_gui_telemetry_read_model]],
[[project_telemetry_gui_controls]], [[project_telemetry_dashboard]].
