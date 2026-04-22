# -*- coding: utf-8 -*-
"""
Регистры управления нейросетевым детектором.
"""
from typing import Annotated

from pydantic import ConfigDict

from multiprocess_framework.modules.data_schema_module import (
    FieldMeta,
    RegisterBase,
)


class NeurounRegisters(RegisterBase):
    # model_path не конфликтует с Pydantic-namespace при protected_namespaces=()
    model_config = ConfigDict(
        validate_assignment=True,
        populate_by_name=True,
        protected_namespaces=(),
    )
    """Регистры управления нейросетевым модулем детекции."""

    enabled: Annotated[
        bool,
        FieldMeta(
            "Включить нейродетекцию",
            info="Включить / отключить нейросетевую детекцию.",
            routing={"channel": "control_neuroun"},
        ),
    ] = False

    confidence_threshold: Annotated[
        float,
        FieldMeta(
            "Порог уверенности",
            info="Минимальный порог уверенности для принятия результата детекции.",
            min=0.0,
            max=1.0,
            transfer_k=100.0,
            round_k=2,
            routing={"channel": "control_neuroun"},
        ),
    ] = 0.5

    model_path: Annotated[
        str,
        FieldMeta(
            "Путь к модели",
            info="Путь к файлу нейросетевой модели (.onnx, .pt и т.д.).",
            routing={"channel": "control_neuroun"},
        ),
    ] = ""
