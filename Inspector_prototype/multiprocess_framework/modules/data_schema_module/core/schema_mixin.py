# -*- coding: utf-8 -*-
"""
SchemaMixin — миксин с методами работы с полями для SchemaBase.

Предоставляет пять логических секций:
    1. Метаданные     — get_field_meta, get_all_fields_meta, get_field_metadata,
                        get_all_metadata, get_field_description, get_field_descriptions
    2. Валидация      — validate_field, get_safe_value
    3. Доступ         — can_modify_field, get_visible_fields, get_editable_fields,
                        get_fields_for_access_level
    4. Маршрутизация  — get_routing_channels, get_fields_for_channel
    5. Значения       — update_field, values_dict

Все методы работают через Annotated[T, FieldMeta(...)]:
метаданные живут в аннотации, значения — как обычные атрибуты Pydantic-модели.

Backward compatibility: RegisterMixin = SchemaMixin (алиас в конце файла).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Tuple

if TYPE_CHECKING:
    from .field_meta import FieldMeta

# Кэш метаданных на уровне модуля: ключ → результат.
# Заполняется один раз при первом вызове для каждого класса/поля.
# Безопасно т.к. model_fields неизменяем после создания класса.
_ALL_FIELDS_META_CACHE: dict[type, dict] = {}
_FIELD_META_CACHE: dict[tuple[type, str], Any] = {}


class SchemaMixin:
    """
    Миксин для SchemaBase.

    Ожидает совместное наследование с pydantic.BaseModel (через SchemaBase).
    Не имеет собственных полей — только методы.
    """

    # =========================================================================
    # 1. Метаданные полей
    # =========================================================================

    @classmethod
    def get_field_meta(cls, field_name: str) -> "FieldMeta | None":
        """
        FieldMeta поля из Annotated[T, FieldMeta(...)], или None если
        поле не имеет аннотации FieldMeta.

        Результат кэшируется per (class, field_name) — O(1) после первого вызова.
        """
        cache_key = (cls, field_name)
        if cache_key not in _FIELD_META_CACHE:
            from .field_meta import FieldMeta as _FieldMeta

            field_info = cls.model_fields.get(field_name)  # type: ignore[attr-defined]
            if field_info is None:
                _FIELD_META_CACHE[cache_key] = None
            else:
                _FIELD_META_CACHE[cache_key] = next(
                    (m for m in field_info.metadata if isinstance(m, _FieldMeta)),
                    None,
                )
        return _FIELD_META_CACHE[cache_key]

    @classmethod
    def get_all_fields_meta(cls) -> dict[str, "FieldMeta"]:
        """
        Словарь {имя_поля: FieldMeta} для всех полей с метаданными.
        Поля без FieldMeta в аннотации не включаются.

        Результат кэшируется per class — O(1) после первого вызова.
        """
        if cls not in _ALL_FIELDS_META_CACHE:
            from .field_meta import FieldMeta as _FieldMeta

            result: dict[str, _FieldMeta] = {}
            for name, field_info in cls.model_fields.items():  # type: ignore[attr-defined]
                meta = next(
                    (m for m in field_info.metadata if isinstance(m, _FieldMeta)),
                    None,
                )
                if meta is not None:
                    result[name] = meta
            _ALL_FIELDS_META_CACHE[cls] = result
        return _ALL_FIELDS_META_CACHE[cls]

    def get_field_metadata(
        self,
        field_name: str,
        lang: str | None = None,
        translation_manager: Any = None,
    ) -> dict[str, Any]:
        """
        Словарь метаданных поля (description, info, min, max, unit и т.д.).

        При передаче translation_manager — info переводится через него.
        Возвращает пустой dict для полей без FieldMeta.
        """
        meta = self.get_field_meta(field_name)
        if meta is None:
            return {}
        d = meta.to_dict(lang)
        if translation_manager and hasattr(translation_manager, "translate_metadata"):
            d["info"] = translation_manager.translate_metadata(d, field="info")
        return d

    def get_all_metadata(
        self,
        lang: str | None = None,
        translation_manager: Any = None,
    ) -> dict[str, dict[str, Any]]:
        """
        Метаданные всех полей с FieldMeta: {имя_поля: metadata_dict}.
        """
        return {
            name: self.get_field_metadata(name, lang, translation_manager)
            for name in self.get_all_fields_meta()
        }

    def get_field_description(
        self,
        field_name: str,
        lang: str | None = None,
        translation_manager: Any = None,
    ) -> str:
        """
        Краткое описание / info поля для UI-подсказок.

        Приоритет: info → description → пустая строка.
        """
        meta = self.get_field_meta(field_name)
        if meta is None:
            return ""
        if translation_manager and hasattr(meta, "to_dict"):
            d = meta.to_dict()
            return translation_manager.translate_metadata(d, field="info")
        info = meta.get_info(lang)
        if info:
            return info
        return meta.get_description(lang)

    def get_field_descriptions(self, separator: str = ".") -> dict[str, str]:
        """Словарь {имя_поля: info/description} для всех полей с FieldMeta."""
        return {
            name: meta.get_info() or meta.get_description()
            for name, meta in self.get_all_fields_meta().items()
        }

    # =========================================================================
    # 2. Валидация значений
    # =========================================================================

    def validate_field(
        self,
        field_name: str,
        value: Any,
        access_level: int = 0,
    ) -> tuple[bool, str | None]:
        """
        Проверить значение поля: права доступа + диапазон [min, max].

        Поля без FieldMeta всегда проходят валидацию (True, None).
        Возвращает (успех, сообщение_об_ошибке | None).
        """
        meta = self.get_field_meta(field_name)
        if meta is None:
            return True, None
        return meta.validate_value(value, access_level)

    def validate_field_value(
        self,
        field_name: str,
        value: Any,
        access_level: int = 0,
    ) -> tuple[bool, str | None]:
        """Псевдоним validate_field() для совместимости со старым API."""
        return self.validate_field(field_name, value, access_level)

    def get_safe_value(self, field_name: str, value: Any) -> Any:
        """
        Применить clamp к числовому значению если есть FieldMeta с min/max.

        Для нечисловых значений возвращает value без изменений.
        """
        meta = self.get_field_meta(field_name)
        if meta is not None and isinstance(value, (int, float)):
            return meta.clamp(value)
        return value

    # =========================================================================
    # 3. Управление доступом
    # =========================================================================

    def can_modify_field(self, field_name: str, access_level: int = 0) -> bool:
        """True если поле разрешено к изменению с данным уровнем доступа."""
        meta = self.get_field_meta(field_name)
        return meta.can_modify(access_level) if meta else True

    def get_visible_fields(self, access_level: int = 0) -> list[str]:
        """Имена полей, видимых пользователю с данным уровнем доступа."""
        result: list[str] = []
        for name in self.model_fields:  # type: ignore[attr-defined]
            meta = self.get_field_meta(name)
            if meta is None or meta.is_visible(access_level):
                result.append(name)
        return result

    def get_editable_fields(self, access_level: int = 0) -> list[str]:
        """Имена полей, доступных для редактирования с данным уровнем доступа."""
        result: list[str] = []
        for name in self.model_fields:  # type: ignore[attr-defined]
            meta = self.get_field_meta(name)
            if meta is None or meta.can_modify(access_level):
                result.append(name)
        return result

    def get_fields_for_access_level(
        self,
        access_level: int = 0,
    ) -> dict[str, dict[str, Any]]:
        """
        Метаданные видимых полей: {имя_поля: metadata_dict}.
        Аналог get_visible_fields(), но сразу с метаданными.
        """
        return {
            name: self.get_field_metadata(name)
            for name in self.model_fields  # type: ignore[attr-defined]
            if (meta := self.get_field_meta(name)) is not None
            and meta.is_visible(access_level)
        }

    # =========================================================================
    # 4. Маршрутизация
    # =========================================================================

    def get_routing_channels(self) -> set[str]:
        """Все уникальные каналы маршрутизации, указанные в FieldMeta полей."""
        channels: set[str] = set()
        for meta in self.get_all_fields_meta().values():
            routing = meta.routing if isinstance(meta.routing, dict) else {}
            ch = routing.get("channel", "")
            if ch:
                channels.add(ch)
        return channels

    def get_fields_for_channel(self, channel: str) -> list[str]:
        """Имена полей, привязанных к указанному каналу маршрутизации."""
        return [
            name
            for name, meta in self.get_all_fields_meta().items()
            if (meta.routing if isinstance(meta.routing, dict) else {}).get("channel") == channel
        ]

    # =========================================================================
    # 5. Операции со значениями
    # =========================================================================

    def build(self) -> Tuple[str, Dict[str, Any]]:
        """
        Dict at Boundary: (manager_name, полный dict полей).

        Имя берётся из поля ``manager_name``, иначе — имя класса.
        Подклассы с кастомной сборкой могут переопределить (legacy).
        """
        name = getattr(self, "manager_name", type(self).__name__)
        return (name, self.model_dump())  # type: ignore[attr-defined]

    def update_field(
        self,
        field_name: str,
        value: Any,
        access_level: int = 0,
    ) -> tuple[bool, str | None]:
        """
        Обновить значение поля с проверкой прав доступа и диапазона.

        Если модель использует validate_assignment=True (SchemaBase),
        Pydantic дополнительно валидирует тип при setattr.

        Возвращает (успех, сообщение_об_ошибке | None).
        """
        valid, error = self.validate_field(field_name, value, access_level)
        if not valid:
            return False, error
        try:
            setattr(self, field_name, value)
            return True, None
        except Exception as exc:
            return False, str(exc)

    def values_dict(self) -> dict[str, Any]:
        """
        Плоский словарь {поле: значение}.

        Эквивалент model_dump(). Сохранён для совместимости со старым кодом;
        в новом коде предпочтительнее использовать model_dump() напрямую.
        """
        return self.model_dump()  # type: ignore[attr-defined]


# Backward compatibility alias
RegisterMixin = SchemaMixin
