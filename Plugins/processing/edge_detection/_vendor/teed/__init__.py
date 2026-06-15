"""Вендоренная модель TEED (Tiny and Efficient Edge Detector).

Источник: https://github.com/xavysp/TEED — автор xavysp, лицензия MIT.
Сеть (~58K параметров) перенесена в ted.py/activations.py как есть.

Веса (BIPED checkpoint) НЕ качаются автоматически (GitHub LFS не отдаёт через
urllib). resolve_weights() ищет готовый файл по списку кандидатов:
  1. явный путь из конфига плагина (weights_path);
  2. ~/.cache/sketch_robot/teed_biped.pth (и legacy teed_biped_10.pth);
  3. ~/.cache/inspector_sketch/teed_biped.pth;
  4. <repo>/data/models/teed/teed_biped.pth.

Получить веса:
  git clone --depth 1 https://github.com/xavysp/TEED.git /tmp/teed
  cp /tmp/teed/checkpoints/BIPED/7/7_model.pth ~/.cache/sketch_robot/teed_biped.pth
"""

from __future__ import annotations

from pathlib import Path

from .ted import TED

__all__ = ["TED", "resolve_weights"]


def _candidates(explicit: str | None) -> list[Path]:
    """Список путей-кандидатов на веса TEED в порядке приоритета."""
    home = Path.home()
    # __file__ = <repo>/Plugins/processing/edge_detection/_vendor/teed/__init__.py
    # parents[5] = <repo> (Inspector_bottles)
    repo_root = Path(__file__).resolve().parents[5]
    out: list[Path] = []
    if explicit:
        out.append(Path(explicit))
    out.extend(
        [
            home / ".cache" / "sketch_robot" / "teed_biped.pth",
            home / ".cache" / "sketch_robot" / "teed_biped_10.pth",
            home / ".cache" / "inspector_sketch" / "teed_biped.pth",
            repo_root / "data" / "models" / "teed" / "teed_biped.pth",
        ]
    )
    return out


def resolve_weights(explicit: str | None = None) -> str:
    """Найти файл весов TEED. Возвращает путь или бросает FileNotFoundError."""
    candidates = _candidates(explicit)
    for p in candidates:
        if p.is_file():
            return str(p)
    listing = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        "Веса TEED не найдены. Положите teed_biped.pth в один из путей:\n  "
        + listing
        + "\nИсточник: https://github.com/xavysp/TEED "
        "(checkpoints/BIPED/7/7_model.pth → teed_biped.pth)"
    )
