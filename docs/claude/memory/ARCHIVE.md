# ARCHIVE.md — история закрытых треков

Этот файл **не грузится** в контекст автоматически. Читать целенаправленно, когда нужен
статус старой фазы, причина давнего решения или контекст «а как мы к этому пришли».
Живое — правила, окружение, открытые долги — в [MEMORY.md](MEMORY.md).

Критерий переноса сюда: механизм закрыт и урок из него уже вынесен в MEMORY.md.
Правило не архивируется никогда — оно должно срабатывать до того, как о нём вспомнят.

---

## Observability Ф2–Ф8 (план observability-unified-routing)

- [Ф2 закрыта](project_f2_closed_2026_08.md) — кроме 2.3b · [Ф2.4 скоуп = строка](project_f2_4_scope_is_a_string.md) — группа заводится конфигом
- [Ф3 внешнее ревью](project_f3_external_review.md) — 8/10; Б-5 рестарт сломан live, Б-6 шторм измерен
- [Ф4 процессоры](project_f4_processors_closed.md) — редакция секретов всегда включена
- [Ф5 сквозное ревью](project_f5_cross_review.md) — 7.5/10, блокеры ФР-1/2/3 · [Ф6.х корзина](project_f6x_review_basket.md) — 5 случаев тестов-невидимок
- [Ф7 сквозное ревью](project_f7_cross_review.md) — 7.5/10, корзина Ф7.х закрыта
- Слои и механика: [аудит смен](project_observability_audit.md) — один писатель, origin в сигнатуре · [четыре слоя конфига](project_observability_config_layers.md) · [control-plane](project_observability_control_plane.md) — ADR-CRM-006 · [симметрия namespace](project_observability_namespace_symmetry.md) · [сессия L3 = TTL](project_observability_session_ttl.md) · [миграция на stdlib](project_observability_stdlib_migration.md) — 64% объёма даёт stats · [брокер подписки 5.11](project_observability_subscription_broker.md)

## Ф7 Phase G — SHM, seqlock, QoS

- [G.3 FrameShm seqlock](project_f7_g3_handoff.md) — torn→0, merge b54b4689
- [G.4 QoS + кольца](project_f7_g4_done.md) — merge e6b1bcca, владение слотами → G.5
- [G.5 владение слотами](project_g5_ownership_decision.md) — оба примитива сразу, GUI copy-out
- [G.7 флип-лесенка](project_f7_g7_flip_ladder.md) — 9 флагов по одному, restore p99 1.4→0.2 мс · [num_consumers из топологии](project_f7_g7_num_consumers.md)

## Cross-tab архитектура (2026-05, Phase B→G)

- [B — domain skeleton](project_cross_tab_phase_b.md) · [C — adapters, 113 тестов](project_cross_tab_phase_c.md) · [D — AppServices + QtEventBus](project_cross_tab_phase_d.md) · [E — миграция вкладок на DI](project_cross_tab_phase_e.md) · [F — удаление legacy](project_cross_tab_phase_f.md) · [G — финальная, ActionBus→commands](project_cross_tab_phase_g.md)

## Конструктор, плагины, вкладки

- [config-driven arch](project_config_driven_arch.md) — GenericProcess + плагины · [Phase 5 ShmRouteNode](project_constructor_phase5.md) · [Phase 6 DEPRECATED](project_constructor_phase6.md) — компоненты удалены 261b90f, сохранены идеи
- [Phase 5 data pipeline](project_phase5_data_pipeline.md) · [Phase 5 полностью](project_phase5_progress.md) — 158 тестов · [Phase 6 UI плагинов](project_plugin_system_phase6.md) · [SystemTopology фазы](project_system_topology_phase1.md) · [вкладка Процессы](project_processes_tab.md)

## Телеметрия (закрытые планы)

- [DB-sink](project_telemetry_db_sink.md) — весь закрыт, долг insert_many · [dashboard + PyQtGraph](project_telemetry_dashboard.md) · [publish-control](project_telemetry_publish_control.md) — ADR-PM-018, errors always-on · [GUI-контролы Ф4.1](project_telemetry_gui_controls.md) · [coherence remediation](project_telemetry_coherence_remediation.md) — Фаза 1 закрыта · [подписка «—» в Processes](project_telemetry_subscription_bug.md) — остаток: late-binding lazy tab

## Pipeline (этапы)

- [демо-рецепт](project_pipeline_demo.md) · [editor ⊥ runtime](project_pipeline_editor_runtime_decoupled.md) — hot-apply готов, не подключён · [live-control этап 1](project_pipeline_live_control_stage1.md) — IPC-мост GUI→PM · [этап 2](project_pipeline_live_control_stage2.md) — live field-write · [видение инкрементальности](project_pipeline_live_incremental_vision.md) — per-process, не full-replace · [node→process→worker](project_pipeline_node_process_worker.md)

## Команды и транспорт

- [comm-system P0](project_comm_system_p0.md) · [command-bus P4.4](project_command_bus_p4_4.md) — CommandManager как библиотека · [command-result bridge](project_command_result_bridge.md) — GUI получает реальный результат

## backend_ctl — история фаз

- [Phase D/E слиты в main](project_backend_ctl_d1_session_isolation.md) — аудит-журнал, валидация, limits · [ultra-ревью 4.5→8.0](project_backend_ctl_ultra_review.md) · [дыры 2026-07](project_backend_ctl_gaps_2026_07.md) — периферия обогнала доказательства · [recorder оставлен](project_backend_ctl_recorder_kept.md) — приговор Task 4.2 снят
- [охота на баги 2026-07-21](project_live_verification_2026_07_21.md) — 17 находок починено, A-10 опровергнута

## Рецепты, прототип, инфраструктура

- [recipe hot-swap](project_recipe_hotswap.md) — кадры после switch решены двухфазной регистрацией очередей, НЕ SHM · [менеджер рецептов](project_recipes_manager.md) — replace_blueprint с rollback
- [калибровка камера↔робот](project_calibration_gui_progress.md) — баг прогресса визарда починен; урок про новые state-корни
- [аудит прототипа 2026-06](project_prototype_audit_2026_06.md) · [carve-out в framework](project_prototype_carveout.md) — domain/adapters отложены · [архивы удалены](project_archives_removed.md) — v1/v2 и backup
- [baseline sentrux 2026-05](project_sentrux_baseline_2026_05.md) · [миграция на claude-kit v1.0.0](project_claude_kit_migration.md)
- [settings MVP рефактор](project_settings_mvp_refactor.md) · [handoff sources-виджет](handoff_sources_widget_refactor.md)
