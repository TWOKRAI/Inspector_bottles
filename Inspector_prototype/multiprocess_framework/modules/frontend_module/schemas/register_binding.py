# -*- coding: utf-8 -*-
"""
RegisterBinding и ResolvedMeta — привязка к регистру и объединённые метаданные.

RegisterBinding: явная привязка компонента к register_name.field_name.
RegisterFieldMeta: сырые метаданные из схемы регистра (min, max, unit, default).
ResolvedMeta: слияние RegisterFieldMeta + переопределения из ComponentConfig.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class RegisterBinding:
    """Привязка компонента к полю регистра."""

    register_name: str
    field_name: str

    @classmethod
    def parse(cls, value: str) -> "RegisterBinding":
        """Парсинг 'register.field' в RegisterBinding."""
        if "." in value:
            parts = value.split(".", 1)
            return cls(register_name=parts[0], field_name=parts[1])
        return cls(register_name="", field_name=value)


@dataclass
class RegisterFieldMeta:
    """Метаданные поля из схемы регистра (dict из get_field_metadata)."""

    min: Optional[float] = None
    max: Optional[float] = None
    default: Any = None
    unit: str = ""
    description: str = ""
    info: str = ""
    access_level: int = 0
    readonly: bool = False
    transfer_k: Optional[float] = None
    round_k: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, meta: Dict[str, Any]) -> "RegisterFieldMeta":
        """Создать из dict (get_field_metadata)."""
        raw = dict(meta) if meta else {}
        return cls(
            min=raw.get("min"),
            max=raw.get("max"),
            default=raw.get("default"),
            unit=raw.get("unit", ""),
            description=raw.get("description", raw.get("info", "")),
            info=raw.get("info", raw.get("description", "")),
            access_level=raw.get("access_level", 0),
            readonly=raw.get("readonly", False),
            transfer_k=raw.get("transfer_k"),
            round_k=raw.get("round_k"),
            raw=raw,
        )


@dataclass
class ResolvedMeta:
    """
    Объединённые метаданные: регистр + переопределения из ComponentConfig.

    Используется для построения UI. Config переопределяет поля регистра.
    """

    label: str
    min_val: float
    max_val: float
    default_val: Any
    unit: str
    description: str
    transfer_k: float
    round_k: int
    access_level: int
    readonly: bool
    raw: Dict[str, Any]

    @classmethod
    def merge(
        cls,
        meta: RegisterFieldMeta,
        config: Any,
        field_name: str = "",
    ) -> "ResolvedMeta":
        """
        Слияние метаданных регистра с переопределениями из конфига.

        config — объект с атрибутами label, transfer_k, round_k (или dict).
        Извлекаем только нужные ключи, чтобы не сериализовать callable и др.
        """
        cfg_dict: Dict[str, Any] = {}
        cfg = config
        if hasattr(cfg, "model_dump"):
            try:
                full = cfg.model_dump()
                for key in (
                    "label",
                    "transfer_k",
                    "round_k",
                    "position",
                    "access_level",
                    "min",
                    "max",
                ):
                    if key in full and full[key] is not None:
                        cfg_dict[key] = full[key]
            except Exception:
                pass
        elif isinstance(cfg, dict):
            for key in (
                "label",
                "transfer_k",
                "round_k",
                "position",
                "access_level",
                "min",
                "max",
            ):
                if key in cfg and cfg[key] is not None:
                    cfg_dict[key] = cfg[key]

        label = cfg_dict.get("label") or meta.description or meta.info or field_name
        access_level = cfg_dict.get("access_level")
        if access_level is None:
            access_level = meta.access_level
        transfer_k = _first_not_none(
            cfg_dict.get("transfer_k"),
            meta.transfer_k,
            1.0,
        )
        round_k = _first_not_none(cfg_dict.get("round_k"), meta.round_k)
        if round_k is None and isinstance(meta.default, (int, float)):
            round_k = 1 if isinstance(meta.default, float) else 0
        if round_k is None:
            round_k = 0

        min_val = _first_not_none(cfg_dict.get("min"), meta.min, 0)
        max_val = _first_not_none(cfg_dict.get("max"), meta.max, 100)
        default_val = meta.default if meta.default is not None else min_val

        return cls(
            label=str(label),
            min_val=float(min_val),
            max_val=float(max_val),
            default_val=default_val,
            unit=meta.unit or "",
            description=meta.info or meta.description or label,
            transfer_k=float(transfer_k),
            round_k=int(round_k),
            access_level=int(access_level),
            readonly=meta.readonly,
            raw=meta.raw,
        )


def _first_not_none(*values: Any) -> Any:
    """Первый не-None из значений."""
    for v in values:
        if v is not None:
            return v
    return None
