"""Backend-зона прототипа: декларативная конфигурация и wiring системы.

Содержит:
  * config/   — system.yaml + Pydantic-схемы дефолтов;
  * topology/ — YAML-blueprint'ы (какие процессы/плагины поднимать);
  * state/    — bootstrap StateStoreManager.

Зеркало `frontend/` (Qt GUI). Runtime-обвязка (entry-points, orchestrator,
GenericProcessApp) намеренно остаётся в корне prototype, а не здесь.
"""
