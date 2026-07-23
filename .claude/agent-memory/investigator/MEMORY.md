# Memory Index

- [K8 TopologyEditorWidget kill](project_k8_topology_editor_kill.md) — виджет DEAD; ловушка __init__.py re-export держит живой TopologyPresenter (Ф8)
- [Гейт топологии ≠ fence](project_state_gate_vs_fence_confusion.md) — rejected/'middleware' = гейт state; таймаут без ответа = fence; драйвер под fence не попадает
- [Атрибуция router-errors](project_router_errors_attribution.md) — errors по точкам считаются арифметикой без патча; QueueRegistry-логи не доходят никуда, RouterStats усечён
- [backend_ctl MCP surface audit 2026-07-23](project_backend_ctl_mcp_surface_audit_2026_07_23.md) — full=true схема-заблокирован на 45/49 тулов; record_start/dump SAFETY_READ молча перезаписывает файл
- [backend_ctl state-транспорт](project_backend_ctl_state_transport_path.md) — драйвер едет по Ф1.1b direct-socket-bridge (не {name}_state drop_oldest); флип FW_STATE транспортно-нейтрален; read-model без revision-gap = truth-hole
- [Overview слеп к потерям](project_overview_blind_to_loss.md) — system_overview аномалии не читают never_drop_loss/evict_blocked/data_evicted; health зелёный при тяжелейшей потере
- [backend_ctl fake-fidelity gap](project_backend_ctl_fake_fidelity_gap.md) — FakeDriver=эхо, ответы хендлеров выписаны руками, live-сверка только у 4 обёрток; logger_sink 0 тестов
