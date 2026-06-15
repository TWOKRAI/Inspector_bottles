"""U2Net Portrait — ONNX-детектор художественных контурных линий портрета.

Источник модели: rembg / NathanUA U-2-Net (u2net_portrait.onnx). Веса НЕ качаются
автоматически — resolve_portrait_weights ищет готовый файл в кэше.
"""

from __future__ import annotations

from pathlib import Path

from .detector import U2NetPortraitDetector

__all__ = ["U2NetPortraitDetector", "resolve_portrait_weights"]


def resolve_portrait_weights(explicit: str | None = None) -> str:
    """Найти u2net_portrait.onnx. Бросает FileNotFoundError, если нет."""
    home = Path.home()
    repo_root = Path(__file__).resolve().parents[5]  # <repo>
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates += [
        home / ".cache" / "sketch_robot" / "u2net_portrait.onnx",
        home / ".cache" / "inspector_sketch" / "u2net_portrait.onnx",
        repo_root / "data" / "models" / "u2net_portrait.onnx",
    ]
    for p in candidates:
        if p.is_file():
            return str(p)
    listing = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        "Веса U2Net Portrait не найдены. Положите u2net_portrait.onnx в один из путей:\n  "
        + listing
        + "\nИсточник: https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_portrait.onnx"
    )
