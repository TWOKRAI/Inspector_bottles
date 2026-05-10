"""Параметры операции захвата кадра из видеофайла."""

from __future__ import annotations

from typing import Annotated, Literal

from multiprocess_framework.modules.data_schema_module import FieldMeta, register_schema

from .base import ProcessingParamsBase


@register_schema("FileInputParamsV3")
class FileInputParams(ProcessingParamsBase):
    """Параметры входной операции из файла (loop при EOF)."""

    type: Literal["file_input"] = "file_input"

    file_path: Annotated[
        str,
        FieldMeta("Путь к файлу", info="Путь к видеофайлу. Поддерживается loop при EOF."),
    ] = ""


__all__ = ["FileInputParams"]
