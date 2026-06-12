"""Реестр архитектур и сборка модели (класс + опциональный угол).

Источники backbone:
- torchvision: mobilenet_v3_large / mobilenet_v3_small (есть всегда при ml-train)
- timm (опционально): mobilenetv4_* алиасы + универсальный passthrough
  `timm/<имя>` — любая из сотен архитектур timm без правок кода.

Модель всегда `MultiHeadModel`: backbone-фичи → голова классов
(+ голова угла sin/cos при angle_head). Выход — tuple(logits, angle|None),
стабильный для ONNX-экспорта.
"""

from __future__ import annotations

import torch
from torch import nn

from Services.ml_train.config import ModelConfig

#: alias → имя модели timm (MobileNetV4, 2024+; актуальные conv/hybrid варианты)
_TIMM_ALIASES = {
    "mobilenetv4_small": "mobilenetv4_conv_small",
    "mobilenetv4_medium": "mobilenetv4_conv_medium",
    "mobilenetv4_large": "mobilenetv4_conv_large",
    "mobilenetv4_hybrid_medium": "mobilenetv4_hybrid_medium",
    "mobilenetv4_hybrid_large": "mobilenetv4_hybrid_large",
}

_TORCHVISION_ARCHS = ("mobilenet_v3_large", "mobilenet_v3_small")


def available_archs() -> dict[str, str]:
    """Имя архитектуры → источник ('torchvision' | 'timm' | 'timm (не установлен)').

    Для GUI/CLI-списка. `timm/<имя>` в перечень не входит (открытое множество).
    """
    try:
        import timm  # noqa: F401

        timm_status = "timm"
    except ImportError:
        timm_status = "timm (не установлен)"
    result = {arch: "torchvision" for arch in _TORCHVISION_ARCHS}
    result.update({alias: timm_status for alias in _TIMM_ALIASES})
    return result


class MultiHeadModel(nn.Module):
    """Backbone (фичи) + голова классов + опциональная голова угла.

    forward → (logits[B,C], angle[B,2] | None). Выход угла — сырой (без
    нормировки): atan2(sin, cos) инвариантен к масштабу вектора.
    """

    def __init__(
        self,
        backbone: nn.Module,
        feature_dim: int,
        num_classes: int,
        dropout: float,
        angle_head: bool,
    ) -> None:
        super().__init__()
        self.backbone = backbone
        self.dropout = nn.Dropout(dropout)
        self.class_head = nn.Linear(feature_dim, num_classes)
        self.angle_head = nn.Linear(feature_dim, 2) if angle_head else None

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor | None]:
        features = self.dropout(self.backbone(x))
        logits = self.class_head(features)
        angle = self.angle_head(features) if self.angle_head is not None else None
        return logits, angle


def build_model(config: ModelConfig, num_classes: int) -> MultiHeadModel:
    """Собрать модель по конфигу.

    Pre: num_classes ≥ 2; config.arch — известный alias либо `timm/<имя>`.
    Post: модель в режиме train, веса backbone — pretrained при config.pretrained
          (и наличии скачиваемых весов).
    """
    if num_classes < 2:
        raise ValueError(f"num_classes должен быть >= 2, получено {num_classes}")
    arch = config.arch
    if arch in _TORCHVISION_ARCHS:
        backbone, feature_dim = _build_torchvision_backbone(arch, config.pretrained)
    elif arch in _TIMM_ALIASES or arch.startswith("timm/"):
        timm_name = _TIMM_ALIASES.get(arch) or arch.removeprefix("timm/")
        backbone, feature_dim = _build_timm_backbone(timm_name, config.pretrained)
    else:
        known = ", ".join(list(_TORCHVISION_ARCHS) + list(_TIMM_ALIASES))
        raise ValueError(f"Неизвестная архитектура '{arch}'. Доступны: {known}, либо timm/<имя>")
    return MultiHeadModel(
        backbone=backbone,
        feature_dim=feature_dim,
        num_classes=num_classes,
        dropout=config.dropout,
        angle_head=config.angle_head,
    )


def _build_torchvision_backbone(arch: str, pretrained: bool) -> tuple[nn.Module, int]:
    """MobileNetV3 из torchvision как экстрактор фич.

    Сохраняем classifier[0] (Linear 960/576→1280/1024 + Hardswish) — это часть
    pretrained-весов; отрезаем только финальный Linear.
    """
    from torchvision import models as tv_models

    builder = getattr(tv_models, arch)
    weights = (
        "IMAGENET1K_V2" if (pretrained and arch == "mobilenet_v3_large") else ("IMAGENET1K_V1" if pretrained else None)
    )
    model = builder(weights=weights)
    # classifier: [Linear, Hardswish, Dropout, Linear] → фичи после Hardswish
    feature_dim = model.classifier[3].in_features
    model.classifier = nn.Sequential(model.classifier[0], model.classifier[1])
    return model, feature_dim


def _build_timm_backbone(timm_name: str, pretrained: bool) -> tuple[nn.Module, int]:
    """Любая модель timm в feature-режиме (num_classes=0 → pooled фичи)."""
    try:
        import timm
    except ImportError as exc:
        raise ImportError(f"Архитектура '{timm_name}' требует timm: pip install timm (extra '.[ml-train]')") from exc
    backbone = timm.create_model(timm_name, pretrained=pretrained, num_classes=0)
    feature_dim = int(backbone.num_features)
    return backbone, feature_dim
