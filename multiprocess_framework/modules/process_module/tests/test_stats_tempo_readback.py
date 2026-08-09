# -*- coding: utf-8 -*-
"""B1 — темп стат-плоскости в ``effective`` и в вердикте ``config.reload``.

Основание — major-13: readback темпа был эхом запроса. Проверка кодом
2026-08-09 показала, что дефект глубже постановки: ветка stats в
``observability_effective`` **не исполнялась вовсе** — она сторожится
``getattr(stats, "config", None) is not None``, а ``StatsManager`` (в отличие от
логгера и ошибок, у которых ``self.config`` ставит ``LoggerCore``) атрибута
``config`` не имеет. Воспроизведено до правки: ``observability_effective(stats=mgr)``
→ ``{}``. Защита была недостижима, и весь темп жил в вердикте как
``unverifiable``.

Числа — вне дефолтов (5.0 / 10.0), см. пояснение в
``statistics_module/tests/test_tempo_knob.py``.
"""

from pathlib import Path
from typing import Any, Dict

from ...statistics_module.core.stats_manager import StatsManager
from ..managers.observability_reload import observability_effective, observability_verified


def _stats(path: Path, **over: Any) -> StatsManager:
    cfg: Dict[str, Any] = {
        "enable_logging": False,
        "channels": {"probe": {"type": "file", "file_path": str(path), "format": "json"}},
    }
    cfg.update(over)
    mgr = StatsManager(manager_name="stats_probe", config=cfg)
    mgr.initialize()
    return mgr


def test_effective_carries_the_stats_plane(tmp_path: Path) -> None:
    """Секция stats в readback вообще существует (до B1 её не было ни разу)."""
    mgr = _stats(tmp_path / "s.json", aggregation_interval=12.0)
    try:
        eff = observability_effective(stats=mgr)
        assert "stats" in eff, "плоскость статистики не отдаёт readback вовсе"
        assert eff["stats"]["aggregation_interval"] == 12.0
    finally:
        mgr.shutdown()


def test_verdict_on_the_tempo_is_confirmed_not_unverifiable(tmp_path: Path) -> None:
    """``config_reload_verified`` на этом ключе перестаёт быть «не проверено»."""
    mgr = _stats(tmp_path / "s.json", aggregation_interval=12.0)
    try:
        mgr.reconfigure(
            {
                "enable_logging": False,
                "channels": {"probe": {"type": "file", "file_path": str(tmp_path / "s.json"), "format": "json"}},
                "aggregation_interval": 36.0,
            }
        )
        verdict = observability_verified(
            {"stats": {"aggregation_interval": 36.0}},
            observability_effective(stats=mgr),
        )
        assert verdict["verdict"] == "confirmed", verdict
        assert "stats.aggregation_interval" not in verdict["unverifiable"]
        assert verdict["checked"] >= 1
    finally:
        mgr.shutdown()


def test_request_below_the_floor_is_reported_failed_with_both_numbers(tmp_path: Path) -> None:
    """Пара к предыдущему: пол остаётся (Р-3б), но вердикт про него не врёт.

    Запрошенные 3.0 не действуют — действует пол 10.0. ``confirmed`` здесь был
    бы ложью, ``unverifiable`` — умолчанием: правда третья, и она в
    ``mismatches`` с обоими числами.
    """
    mgr = _stats(tmp_path / "s.json", aggregation_interval=3.0)
    try:
        verdict = observability_verified(
            {"stats": {"aggregation_interval": 3.0}},
            observability_effective(stats=mgr),
        )
        assert verdict["verdict"] == "failed", verdict
        mismatch = [m for m in verdict["mismatches"] if m["key"] == "stats.aggregation_interval"]
        assert mismatch, verdict
        assert mismatch[0]["expected"] == 3.0 and mismatch[0]["actual"] == 10.0
    finally:
        mgr.shutdown()
