"""Тесты Task 2.7: схема DiscoverySection и загрузка конфига с override."""

from __future__ import annotations

from pathlib import Path

import yaml

from multiprocess_prototype.backend.config.schemas import (
    DiscoverySection,
    load_system_config,
)


def test_discovery_section_defaults() -> None:
    """DiscoverySection() без аргументов даёт правильные defaults."""
    section = DiscoverySection()
    assert section.plugin_paths == ["Plugins"]
    assert section.service_paths == ["Services"]
    assert section.auto_discover is True


def test_load_system_config_with_overrides(tmp_path: Path) -> None:
    """override plugin_paths имеет приоритет над system.yaml."""
    # Создаём system.yaml с базовым путём
    system_yaml = tmp_path / "system.yaml"
    system_yaml.write_text(
        yaml.dump({"discovery": {"plugin_paths": ["Plugins"]}}),
        encoding="utf-8",
    )

    # Создаём user_overrides.yaml с кастомным путём
    overrides_yaml = tmp_path / "user_overrides.yaml"
    overrides_yaml.write_text(
        yaml.dump({"discovery": {"plugin_paths": ["/custom"]}}),
        encoding="utf-8",
    )

    result = load_system_config(system_yaml)

    # Override должен заменить базовый путь
    assert result.discovery.plugin_paths == ["/custom"]


def test_load_system_config_override_partial_merge(tmp_path: Path) -> None:
    """Частичный override не перетирает незатронутые поля (auto_discover остаётся True)."""
    # system.yaml с двумя полями discovery
    system_yaml = tmp_path / "system.yaml"
    system_yaml.write_text(
        yaml.dump({"discovery": {"plugin_paths": ["Plugins"], "auto_discover": True}}),
        encoding="utf-8",
    )

    # user_overrides.yaml содержит только plugin_paths — auto_discover отсутствует
    overrides_yaml = tmp_path / "user_overrides.yaml"
    overrides_yaml.write_text(
        yaml.dump({"discovery": {"plugin_paths": ["/extra"]}}),
        encoding="utf-8",
    )

    result = load_system_config(system_yaml)

    # Override применился к plugin_paths
    assert result.discovery.plugin_paths == ["/extra"]
    # auto_discover НЕ перетёрт (deep-merge сохраняет незатронутые поля)
    assert result.discovery.auto_discover is True
