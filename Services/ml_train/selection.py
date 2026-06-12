"""RunRegistry — каталог прогонов обучения и выбор лучшей модели.

Сканирует runs_dir: прогон = подпапка с config.yaml + metrics.json
(пишет Trainer). Без torch — сравнение и выбор доступны в любом окружении
(например, из GUI-процесса без ML-стека).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from Services.ml_train.config import _MINIMIZE_METRICS

logger = logging.getLogger(__name__)


@dataclass
class RunInfo:
    """Сводка одного прогона."""

    name: str
    run_dir: Path
    arch: str
    monitor: str
    best_epoch: int
    metrics: dict[str, Any] = field(default_factory=dict)  # метрики лучшей эпохи (val)
    test_metrics: dict[str, Any] | None = None
    checkpoint: Path | None = None  # best.pt (None — прогон без чекпоинта)

    def metric(self, name: str) -> float | None:
        """Значение метрики лучшей эпохи (или None)."""
        value = self.metrics.get(name)
        return float(value) if isinstance(value, (int, float)) else None


class RunRegistry:
    """Каталог прогонов в runs_dir.

    Использование:
        reg = RunRegistry("data/ml_train/runs")
        reg.scan()
        reg.best("balanced_accuracy")   # → RunInfo лучшего прогона
        reg.summary()                   # → строки для таблицы/GUI
    """

    def __init__(self, runs_dir: str | Path) -> None:
        self._dir = Path(runs_dir)
        self._runs: dict[str, RunInfo] = {}

    def scan(self) -> dict[str, RunInfo]:
        """Пересканировать каталог. Битые прогоны пропускаются с warning."""
        self._runs = {}
        if not self._dir.is_dir():
            logger.warning("RunRegistry: папка не найдена: %s", self._dir)
            return {}
        for run_dir in sorted(p for p in self._dir.iterdir() if p.is_dir()):
            try:
                info = self._load_run(run_dir)
            except Exception as exc:  # noqa: BLE001 — каталог не падает из-за одного прогона
                logger.warning("RunRegistry: пропуск %s — %s", run_dir.name, exc)
                continue
            if info is not None:
                self._runs[info.name] = info
        logger.info("RunRegistry: найдено прогонов: %d (%s)", len(self._runs), self._dir)
        return dict(self._runs)

    def names(self) -> list[str]:
        return list(self._runs.keys())

    def get(self, name: str) -> RunInfo | None:
        return self._runs.get(name)

    def best(self, metric: str = "balanced_accuracy") -> RunInfo | None:
        """Лучший прогон по метрике (направление выводится из имени метрики).

        Post: None, если ни у одного прогона нет этой метрики или чекпоинта.
        """
        minimize = metric in _MINIMIZE_METRICS
        candidates = [
            (run.metric(metric), run)
            for run in self._runs.values()
            if run.metric(metric) is not None and run.checkpoint is not None
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda pair: pair[0], reverse=not minimize)
        return candidates[0][1]

    def summary(self, sort_by: str = "balanced_accuracy") -> list[dict[str, Any]]:
        """Строки для таблицы сравнения (отсортированы по метрике, лучшие сверху)."""
        minimize = sort_by in _MINIMIZE_METRICS
        rows = [
            {
                "run": run.name,
                "arch": run.arch,
                "best_epoch": run.best_epoch,
                "monitor": run.monitor,
                "accuracy": run.metric("accuracy"),
                "balanced_accuracy": run.metric("balanced_accuracy"),
                "angle_mae_deg": run.metric("angle_mae_deg"),
                "checkpoint": str(run.checkpoint) if run.checkpoint else None,
            }
            for run in self._runs.values()
        ]
        rows.sort(
            key=lambda r: (r[sort_by] is None, (r[sort_by] or 0) * (1 if minimize else -1)),
        )
        return rows

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _load_run(self, run_dir: Path) -> RunInfo | None:
        metrics_path = run_dir / "metrics.json"
        config_path = run_dir / "config.yaml"
        if not metrics_path.is_file() or not config_path.is_file():
            return None  # не прогон (или ещё идёт обучение)
        final = json.loads(metrics_path.read_text(encoding="utf-8"))
        raw_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        best = final.get("best") or {}
        checkpoint = run_dir / "best.pt"
        return RunInfo(
            name=run_dir.name,
            run_dir=run_dir,
            arch=str(raw_cfg.get("model", {}).get("arch", "?")),
            monitor=str(final.get("monitor", "?")),
            best_epoch=int(final.get("best_epoch", -1)),
            metrics={k: v for k, v in best.items() if not isinstance(v, (list, dict))},
            test_metrics=final.get("test"),
            checkpoint=checkpoint if checkpoint.is_file() else None,
        )
