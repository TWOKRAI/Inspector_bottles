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


## Перенесено из индекса 2026-09-05 — закрытые и спящие треки

Сжатие MEMORY.md по требованию хука (22.3k → ≤ 17.1k символов). Строки перенесены дословно,
урок каждого уже вынесен в MEMORY.md/CRAFT.md. Трек оживает — строка возвращается в индекс.

- [observation-port: Ф0–Ф5 ЗАКРЫТЫ](project_observation_port_progress.md) — порт = единственный писатель чисел, StatsManager стал видом; ревью вернуло 3 блокера, все закрыты; гейт 8930
- [Transport hub](project_transport_router_hub.md) — P0-P2 DONE; P3 отложен · [иерархический адрес](project_hierarchical_addressing.md) — целевое: процесс → воркер → глубже
- [Авто-рестарт всех процессов](project_all_process_autorestart.md) — механизм исполнен Ф4-добор (ADR-PMM-015); хаб+chain-health → Ф5
- [Line filter](project_line_filter_feature.md) — 0-3 DONE; overlay_draw пишет frame
- [Device hub](project_device_hub.md) — always-on, YAML-протоколы, Ф0-5 DONE; NEXT device-tree-recipe
- [Draw mode rework](project_draw_mode_rework.md) — feat/draw-mode-rework; hardware pending
- [Pult panel](project_pult_control_panel.md) — контролы→сигналы; robot_draw live
- [Phone gateway](project_phone_gateway_service.md) — v1 готов, GUI follow-up
- [Gorynych PyPI deferred](project_gorynych_pypi_deferred.md) — триггеры: ок работодателя + потребитель + прод
- [Component Design System](project_component_scoped_styles.md) — DEFERRED

### Закрытые треки — открытые концы (бывшая секция индекса)
- Observability: [Ф2–Ф8 + роадмап](project_f8_review_and_stitching.md) — актуальное в plans/observability-roadmap.md · [хвост-ремонт](project_observability_tail_repair.md) — гейт 6855×3; вход в этап 6 открыт · [ошибки идут в logger, не error_manager](project_observability_store_error_routing.md) — store-tap нужен на ОБА, live-boot вскрыл · [telemetry read-model ADR-136](project_gui_telemetry_read_model.md) · [self-publish DB-sink](project_telemetry_self_publish.md) · [webcam фриз](project_webcam_sketch_freeze.md) — IPC-шторм · [gui задушен очередью](project_gui_system_queue_storm.md) — гонка тихой потери
- Конструктор/GUI: [фазы DONE](project_generic_process_vision.md) — GenericProcess deprecated · [Ф7 Phase G 8.0](project_phase_g_final_review.md) — seqlock, QoS-кольца SHM, флип-лесенка · [Registries v2](project_service_registry.md) — ADR-129…132 · [Pipeline recipe-launch](project_pipeline_recipe_driven_launch.md) — hot-apply не подключён · [Switch stale](project_switch_routing_stale.md) — live через PM-хаб
- [Fencing-тест ADR-SS-019](project_fencing_test_race.md) — ghost-гонка закрыта · [fencing-token топологии](project_topology_fencing_token.md) — исполнено Ф4.2: дроп по per-sender incarnation, НЕ epoch
