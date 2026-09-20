# Memory Index

- [K8 TopologyEditorWidget kill](project_k8_topology_editor_kill.md) — виджет DEAD; ловушка __init__.py re-export держит живой TopologyPresenter (Ф8)
- [Гейт топологии ≠ fence](project_state_gate_vs_fence_confusion.md) — rejected/'middleware' = гейт state; таймаут без ответа = fence; драйвер под fence не попадает
- [Атрибуция router-errors](project_router_errors_attribution.md) — errors по точкам считаются арифметикой без патча; QueueRegistry-логи не доходят никуда, RouterStats усечён
- [backend_ctl MCP surface audit 2026-07-23](project_backend_ctl_mcp_surface_audit_2026_07_23.md) — full=true схема-заблокирован на 45/49 тулов (устаревшие числа, см. full-flag-schema-gap); record_start/dump SAFETY_READ молча перезаписывает файл
- [backend_ctl state-транспорт](project_backend_ctl_state_transport_path.md) — драйвер едет по Ф1.1b direct-socket-bridge (не {name}_state drop_oldest); флип FW_STATE транспортно-нейтрален; read-model без revision-gap = truth-hole
- [Overview слеп к потерям — РЕШЕНО 2026-08-23](project_overview_blind_to_loss.md) — Task Т.2 добавил queue_data_loss/control_plane_loss в anomalies; запись — история болезни, не живой баг
- [backend_ctl fake-fidelity gap](project_backend_ctl_fake_fidelity_gap.md) — FakeDriver=эхо, ответы хендлеров выписаны руками, live-сверка только у 4 обёрток; logger_sink 0 тестов
- [Основания лог-плоскости для Ф2.2](project_logging_foundations_2_2.md) — бенчи stdlib/pico/наш стек + вердикт «семантику брать, рантайм нет»; OTel Logs = Development
- [backend_ctl full=true схема-блок — ПОДТВЕРЖДЕНО HEAD 2026-08-28](project_backend_ctl_full_flag_schema_gap.md) — воспроизведено jsonschema.validate: 44/50 тулов отвергают full=true; долг с 2026-08-12 (observability-dx трек Г), не закрыт
- [Инвентарь _log_error (Task 1.3)](project_log_error_inventory_task_1_3.md) — 315 точек (A240/B51/C14/W10); 252≠315≠226 считают РАЗНОЕ; страж «один разъём» столкнётся с 46 парами из ADR-PM-030
- [backend_ctl прицельные подписки-сироты](project_backend_ctl_targeted_subscription_residual.md) — Task 5.11 брокер закрыл HR-2 ghost-RST только для watch_like_gui/state.**; targeted observability_tail/log_tail/ui_tap сиротеют на креше клиента — назван самим кодом (process_manager_process.py:2800-2804), не закрыт
