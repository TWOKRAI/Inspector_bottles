5.2 Новые модули (будущее)
Модуль	Назначение	Приоритет
health_module	Centralized health checks, readiness/liveness probes, HTTP endpoint для Prometheus	P3
metrics_export_module	Экспорт метрик в OpenTelemetry/Prometheus формат	P3
event_bus_module	Pub/sub по типу события (альтернатива command-based)	P4
plugin_module	Hot-reload плагинов для ProcessModule	P4
5.3 Архитектурные улучшения
Tiered init.py — группировка экспортов по уровням (см. §3)
Единый module count — зафиксировать "18 модулей" везде
Test parity — все модули минимум 20+ тестов
Platform matrix — docs/PLATFORM_NOTES.md (spawn vs fork, SharedMemory, signals)