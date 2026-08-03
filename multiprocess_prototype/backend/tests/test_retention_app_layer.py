# -*- coding: utf-8 -*-
"""Ф6.9 — ретеншен задан слоем ПРИЛОЖЕНИЯ, а не остался нулём фреймворка.

Находка Н-3 живого прогона (2026-08-03): ``retention_days=0`` и
``retention_total_mb=0`` пришли из слоя ``framework``, приложение их не
задавало — чистка была выключена по умолчанию при 471 МБ в ``logs/``.

Проверка идёт по НАСТОЯЩЕМУ ``system.yaml``, а не по литералу в тесте:
литерал доказывал бы, что автор теста умеет писать словарь. Здесь важно ровно
то, что владелец увидит на живом стенде в ``introspect.observability`` —
чей это слой.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from multiprocess_framework.modules.process_module.configs.observability_config import (
    expand_observability,
)
from multiprocess_framework.modules.process_module.configs.observability_layers import (
    LAYER_APP,
    ObservabilityLayers,
)

SYSTEM_YAML = Path(__file__).resolve().parents[1] / "config" / "system.yaml"


def _app_section() -> dict:
    raw = yaml.safe_load(SYSTEM_YAML.read_text(encoding="utf-8"))
    return raw.get("observability") or {}


class TestRetentionOwnedByApp:
    def test_both_policies_are_set_and_non_zero(self) -> None:
        """Обе политики заданы и включены: ноль — это «выключено», а не «дефолт»."""
        section = _app_section()

        assert section.get("retention_days", 0) > 0, "retention_days остался выключенным"
        assert section.get("retention_total_mb", 0) > 0, "retention_total_mb остался выключенным"

    def test_provenance_names_the_app_layer(self) -> None:
        """Провенанс обязан назвать app — иначе владелец ищет причину не в том файле."""
        layers = ObservabilityLayers(app=_app_section(), app_source="backend/config/system.yaml")
        prov = layers.provenance()

        for key in ("retention_days", "retention_total_mb"):
            assert prov[key]["layer"] == LAYER_APP, f"{key} приписан слою {prov[key]}"
            assert prov[key]["source"] == "backend/config/system.yaml"

    def test_values_reach_the_logger_manager_config(self) -> None:
        """Слой без раскладки — половина пути: значения обязаны доехать до менеджера.

        ``expand_observability`` отдаёт ретеншен только секции ``logger``
        (один каталог — один хозяин), и именно этот словарь получает
        ``LoggerManager``.
        """
        expanded = expand_observability(_app_section())

        assert expanded["logger"]["retention_days"] == _app_section()["retention_days"]
        assert expanded["logger"]["retention_total_mb"] == _app_section()["retention_total_mb"]
        assert expanded["logger"]["retention_sweep_interval_sec"] > 0, (
            "интервал фонового свипа нулевой — чистка снова ждёт рестарта"
        )
        assert "retention_days" not in expanded["error"], "второй хозяин каталога логов"
