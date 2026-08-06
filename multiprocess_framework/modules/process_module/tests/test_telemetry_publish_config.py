# -*- coding: utf-8 -*-
"""Тесты TelemetryPublishConfig (PC 1.1) — контракт публикации телеметрии.

Acceptance 1.1:
  - резолв метрики с дефолтом/override (наследование default_interval_sec);
  - неизвестная метрика → (enabled=True, default_interval_sec);
  - выключенная метрика → enabled=False;
  - from_dict/to_dict round-trip (Dict at Boundary).

Acceptance 2.3 (валидация metrics-ключей против каталога метрик):
  - опечатка в имени метрики → unknown_metrics() её ловит;
  - все ключи известны → unknown_metrics() пуст.
"""

from __future__ import annotations

from multiprocess_framework.modules.process_module.configs import (
    MetricRule,
    TelemetryPublishConfig,
)
from multiprocess_framework.modules.process_module.configs.telemetry_publish_config import (
    gated_metrics,
)

# Ф8.1: каталог метрик наполняется ИМПОРТОМ производителей, а не литералом в
# configs/. Этот модуль спрашивает каталог, значит обязан импортировать тех, кто
# его наполняет, — иначе в одиночном прогоне каталог пуст и «опечатка не
# услышана», а в полном зелено, потому что производителей импортировал сосед.
# Зависимость от порядка тестов, воспроизведённая при написании этих проверок.
import multiprocess_framework.modules.process_module.heartbeat.process_heartbeat  # noqa: F401,E402
import multiprocess_framework.modules.process_module.heartbeat.telemetry  # noqa: F401,E402
import pytest  # noqa: E402


class TestUnknownMetrics:
    def test_typo_metric_is_reported(self) -> None:
        """Опечатка в имени метрики (``latency`` вместо ``latency_ms``) → в unknown_metrics()."""
        cfg = TelemetryPublishConfig(metrics={"latency": MetricRule(interval_sec=0.5)})
        assert cfg.unknown_metrics() == {"latency"}

    def test_all_known_metrics_empty(self) -> None:
        """Все ключи metrics из каталога → unknown_metrics() пуст."""
        cfg = TelemetryPublishConfig(metrics={m: MetricRule() for m in gated_metrics()})
        assert cfg.unknown_metrics() == set()

    def test_empty_metrics_empty(self) -> None:
        """Пустой metrics (дефолт) → unknown_metrics() пуст."""
        cfg = TelemetryPublishConfig()
        assert cfg.unknown_metrics() == set()

    def test_mixed_known_and_unknown(self) -> None:
        """Смесь известных и неизвестных ключей → в unknown_metrics() только вторые."""
        cfg = TelemetryPublishConfig(metrics={"fps": MetricRule(), "typo_metric": MetricRule(), "shm": MetricRule()})
        assert cfg.unknown_metrics() == {"typo_metric"}


class TestResolve:
    def test_unknown_metric_enabled_with_default(self) -> None:
        """Метрика не в metrics → включена по дефолту с default_interval_sec."""
        cfg = TelemetryPublishConfig(default_interval_sec=2.0)
        enabled, interval = cfg.resolve("fps")
        assert enabled is True
        assert interval == 2.0

    def test_rule_without_interval_inherits_default(self) -> None:
        """Правило есть, interval_sec=None → наследует default_interval_sec."""
        cfg = TelemetryPublishConfig(
            default_interval_sec=1.5,
            metrics={"fps": MetricRule(enabled=True)},
        )
        enabled, interval = cfg.resolve("fps")
        assert enabled is True
        assert interval == 1.5

    def test_rule_interval_override(self) -> None:
        """Правило задаёт свой interval_sec → он и возвращается."""
        cfg = TelemetryPublishConfig(
            default_interval_sec=1.0,
            metrics={"shm": MetricRule(interval_sec=5.0)},
        )
        enabled, interval = cfg.resolve("shm")
        assert enabled is True
        assert interval == 5.0

    def test_disabled_metric(self) -> None:
        """Выключенная метрика → enabled=False (не публиковать/не считать)."""
        cfg = TelemetryPublishConfig(metrics={"cycle_duration_ms": MetricRule(enabled=False)})
        enabled, _ = cfg.resolve("cycle_duration_ms")
        assert enabled is False

    def test_disabled_metric_still_reports_interval(self) -> None:
        """Даже у выключенной метрики интервал резолвится (наследование)."""
        cfg = TelemetryPublishConfig(
            default_interval_sec=3.0,
            metrics={"latency_ms": MetricRule(enabled=False)},
        )
        enabled, interval = cfg.resolve("latency_ms")
        assert enabled is False
        assert interval == 3.0


class TestDefaults:
    def test_empty_config_all_enabled(self) -> None:
        """Пустой конфиг → любая метрика включена с дефолтным интервалом 1.0."""
        cfg = TelemetryPublishConfig()
        assert cfg.default_interval_sec == 1.0
        assert cfg.metrics == {}
        for m in ("fps", "latency_ms", "effective_hz", "cycle_duration_ms", "shm", "anything"):
            enabled, interval = cfg.resolve(m)
            assert enabled is True
            assert interval == 1.0


class TestDictBoundary:
    def test_from_dict_none_gives_defaults(self) -> None:
        cfg = TelemetryPublishConfig.from_dict(None)
        assert cfg.default_interval_sec == 1.0
        assert cfg.metrics == {}

    def test_from_dict_partial(self) -> None:
        """Частичный dict (из конфига процесса) → остальное дефолты; вложенные
        правила коерсятся в MetricRule."""
        cfg = TelemetryPublishConfig.from_dict(
            {
                "default_interval_sec": 2.0,
                "metrics": {
                    "fps": {"enabled": True, "interval_sec": 1.0},
                    "cycle_duration_ms": {"enabled": False},
                    "shm": {"interval_sec": 5.0},
                },
            }
        )
        assert cfg.default_interval_sec == 2.0
        assert isinstance(cfg.metrics["fps"], MetricRule)
        assert cfg.resolve("fps") == (True, 1.0)
        assert cfg.resolve("cycle_duration_ms")[0] is False
        assert cfg.resolve("cycle_duration_ms")[1] == 2.0  # наследует default
        assert cfg.resolve("shm") == (True, 5.0)

    def test_round_trip(self) -> None:
        """to_dict → from_dict → эквивалентная конфигурация (Dict at Boundary)."""
        original = TelemetryPublishConfig(
            default_interval_sec=2.5,
            metrics={
                "fps": MetricRule(enabled=True, interval_sec=1.0),
                "shm": MetricRule(enabled=False),
            },
        )
        as_dict = original.to_dict()
        assert isinstance(as_dict, dict)
        restored = TelemetryPublishConfig.from_dict(as_dict)
        assert restored.to_dict() == as_dict
        assert restored.resolve("fps") == (True, 1.0)
        assert restored.resolve("shm")[0] is False

    def test_unknown_keys_ignored(self) -> None:
        """Неизвестные ключи игнорируются (SchemaBase extra=ignore), не падает."""
        cfg = TelemetryPublishConfig.from_dict({"default_interval_sec": 1.0, "totally_unknown": 123})
        assert cfg.default_interval_sec == 1.0


class TestEmptyCatalogIsNotAVerdict:
    """Ф8.1: пустой каталог означает «судить не по чему», а не «известных нет».

    Пока каталог был кортежем-литералом, он существовал всегда. Теперь он
    наполняется импортом производителей, и процесс, который телеметрию не
    считает, законно видит его пустым. Без этой ветки КАЖДЫЙ ключ ``metrics``
    объявлялся бы опечаткой — ложная тревога на ровном месте.

    Пара обязательна: «пустой каталог молчит» без «полный каталог говорит»
    зелено и у реализации, которая не жалуется никогда.
    """

    def test_an_empty_catalog_accuses_nobody(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from multiprocess_framework.modules.process_module.configs import telemetry_publish_config as модуль

        monkeypatch.setattr(модуль, "declared_metrics", lambda: ())
        cfg = TelemetryPublishConfig(metrics={"что_угодно": MetricRule()})
        assert cfg.unknown_metrics() == set()

    def test_a_full_catalog_still_names_the_typo(self) -> None:
        cfg = TelemetryPublishConfig(metrics={"latency": MetricRule()})
        assert cfg.unknown_metrics() == {"latency"}, "опечатка перестала быть слышной"
