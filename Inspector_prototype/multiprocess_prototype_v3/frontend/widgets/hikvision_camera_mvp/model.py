# multiprocess_prototype_v3/frontend/widgets/hikvision_camera_mvp/model.py
"""HikvisionCameraMvpModel — регистры и бизнес-правила (границы из HikvisionParamRow / CameraRegisters)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from frontend_module.interfaces import IRegistersManagerGui

from multiprocess_prototype_v3.registers.schemas.camera_tab import (
    CAMERA_REGISTER,
    HikvisionParamRow,
    build_hikvision_param_rows,
)

from .schemas import HikvisionCameraMvpUiConfig


class HikvisionCameraMvpModel:
    """Чтение/запись CAMERA_REGISTER по рядам из build_hikvision_param_rows."""

    def __init__(
        self,
        *,
        rm: Optional[IRegistersManagerGui],
        ui: HikvisionCameraMvpUiConfig,
    ) -> None:
        self._rm = rm
        self._rows: List[HikvisionParamRow] = build_hikvision_param_rows(
            param_display=ui.param_display,
        )

    @property
    def param_rows(self) -> List[HikvisionParamRow]:
        return self._rows

    def read_params_from_register(self) -> Tuple[float, ...]:
        """Значения полей регистра в порядке param_rows; fallback — default_value."""
        if self._rm is None:
            return tuple(r.default_value for r in self._rows)
        reg = self._rm.get_register(CAMERA_REGISTER)
        if not reg:
            return tuple(r.default_value for r in self._rows)
        out: list[float] = []
        for row in self._rows:
            v = getattr(reg, row.register_field, row.default_value)
            out.append(float(v))
        return tuple(out)

    def apply_params_to_register(self, params: Dict[str, Any]) -> None:
        """Записать в регистр (ключи — api_key из ответа камеры)."""
        if not params or self._rm is None:
            return
        for row in self._rows:
            if row.api_key in params:
                self._rm.set_field_value(
                    CAMERA_REGISTER,
                    row.register_field,
                    float(params[row.api_key]),
                )

    def get_params_for_set(
        self,
        fallback_from_lines: Callable[[], Tuple[float, ...]],
    ) -> Tuple[float, ...]:
        """Источник для Set Parameters: регистр при наличии rm, иначе fallback из View."""
        if self._rm is not None:
            return self.read_params_from_register()
        return fallback_from_lines()

    def clamp_parameters(self, values: Sequence[float]) -> Tuple[float, ...]:
        """Привести каждое значение к [min_val, max_val] по ряду."""
        if len(values) != len(self._rows):
            raise ValueError(
                f"Ожидалось {len(self._rows)} значений, получено {len(values)}"
            )
        out: list[float] = []
        for row, v in zip(self._rows, values):
            x = float(v)
            out.append(max(row.min_val, min(row.max_val, x)))
        return tuple(out)

    def parameters_out_of_range(self, values: Sequence[float]) -> List[str]:
        """Список сообщений для параметров вне диапазона (до clamp)."""
        issues: List[str] = []
        if len(values) != len(self._rows):
            issues.append(f"Число значений ({len(values)}) не совпадает с числом параметров.")
            return issues
        for row, v in zip(self._rows, values):
            try:
                x = float(v)
            except (TypeError, ValueError):
                issues.append(f"{row.label} ({row.api_key}): не число.")
                continue
            if x < row.min_val or x > row.max_val:
                issues.append(
                    f"{row.label} ({row.api_key}): {x} вне [{row.min_val}, {row.max_val}]."
                )
        return issues
