# -*- coding: utf-8 -*-
"""
DataReference — ссылки на другие модели/ресурсы.

Используется для хранения легковесных ссылок в конфиге/моделях
без дублирования данных.
"""
from typing import Any, Callable, Dict, Optional


class DataReference:
    """Ссылка на другой объект данных."""

    def __init__(self, ref_id: str, resolver: Optional[Callable[[str], Any]] = None):
        """
        Args:
            ref_id: Идентификатор ссылки (например, "process:main" или "component:xyz")
            resolver: Функция разрешения ссылки по ref_id
        """
        self.ref_id = ref_id
        self.resolver = resolver
        self._cached: Optional[Any] = None

    def resolve(self) -> Optional[Any]:
        """Разрешить ссылку через resolver."""
        if self._cached is not None:
            return self._cached

        if self.resolver:
            self._cached = self.resolver(self.ref_id)
            return self._cached

        return None

    def to_dict(self) -> Dict[str, Any]:
        """Представление ссылки как словаря."""
        return {"_ref": True, "ref_id": self.ref_id}

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        resolver: Optional[Callable[[str], Any]] = None,
    ) -> "DataReference":
        """Создать ссылку из словаря."""
        return cls(data.get("ref_id", ""), resolver)

    def __repr__(self) -> str:  # pragma: no cover
        return f"DataReference(ref_id='{self.ref_id}')"


def is_reference(value: Any) -> bool:
    """Проверить, является ли значение ссылкой."""
    return isinstance(value, DataReference) or (
        isinstance(value, dict) and value.get("_ref") is True
    )


def convert_reference_to_data(
    ref: Any,
    resolver: Optional[Callable[[str], Any]] = None,
) -> Optional[Any]:
    """Конвертировать ссылку в данные."""
    if isinstance(ref, DataReference):
        return resolver(ref.ref_id) if resolver else ref.resolve()

    if isinstance(ref, dict) and ref.get("_ref") is True:
        ref_obj = DataReference.from_dict(ref, resolver)
        return ref_obj.resolve()

    return None


def convert_all_references(
    data: Any,
    resolver: Optional[Callable[[str], Any]] = None,
    max_depth: int = 10,
    current_depth: int = 0,
) -> Any:
    """Рекурсивно конвертировать все ссылки в структуре данных."""
    if current_depth >= max_depth:
        return data

    if is_reference(data):
        resolved = convert_reference_to_data(data, resolver)
        return (
            convert_all_references(resolved, resolver, max_depth, current_depth + 1)
            if resolved is not None
            else data
        )

    if isinstance(data, dict):
        return {
            k: convert_all_references(v, resolver, max_depth, current_depth + 1)
            for k, v in data.items()
        }

    if isinstance(data, list):
        return [
            convert_all_references(v, resolver, max_depth, current_depth + 1)
            for v in data
        ]

    return data
