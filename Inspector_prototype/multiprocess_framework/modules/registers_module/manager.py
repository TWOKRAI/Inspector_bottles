# -*- coding: utf-8 -*-
"""
Обобщённый менеджер регистров.

Не зависит от конкретных классов регистров: принимает словарь имя -> экземпляр Pydantic-модели.
Поддерживает get_register, get_field_metadata (включая routing), validate_field_value, model_dump_all/model_validate_all.
Расширение для frontend: subscribe_all, set_field_value, доставка register_update
    (register_dispatch / routing.process_targets / connection_map).
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .interfaces import IRegistersManager


class RegistersManager:
    """
    Менеджер регистров на основе словаря имя -> экземпляр модели.
    Каждый процесс создаёт свой экземпляр со своим набором регистров.
    connection_map: опциональный override — register_name -> имя процесса для register_update
        (если нет process_targets в routing поля и нет register_dispatch на классе).
    send_callback: вызывается при изменении регистра, если есть хотя бы одна цель доставки.
    """

    def __init__(
        self,
        registers: Optional[Dict[str, Any]] = None,
        connection_map: Optional[Dict[str, str]] = None,
        send_callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]] = None,
    ):
        """
        Args:
            registers: Словарь {имя_регистра: экземпляр_модели}. Если None — пустой менеджер.
            connection_map: {register_name: process_name} — fallback для send_callback (см. ROUTING_GLOSSARY.md).
            send_callback: (channel, register_name, field_name, value, snapshot) — вызов при изменении.
        """
        self._registers: Dict[str, Any] = dict(registers) if registers else {}
        self._connection_map: Dict[str, str] = dict(connection_map) if connection_map else {}
        self._send_callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]] = send_callback
        self._global_observers: List[Callable[[str, str, Any], None]] = []
        self._field_observers: Dict[Tuple[str, str], List[Callable[[Any], None]]] = defaultdict(list)

    def get_register(self, name: str) -> Optional[Any]:
        """Получить экземпляр регистра по имени."""
        return self._registers.get(name)

    def set_connection(self, register_name: str, backend_channel: str) -> None:
        """Привязать регистр к бэкенд-каналу (connection)."""
        self._connection_map[register_name] = backend_channel

    def set_send_callback(self, callback: Optional[Callable[[str, str, str, Any, Dict[str, Any]], None]]) -> None:
        """Установить callback для отправки изменений в бэкенд."""
        self._send_callback = callback

    def subscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
    ) -> None:
        """Подписать callback(value) на изменение поля."""
        key = (register_name, field_name)
        if callback not in self._field_observers[key]:
            self._field_observers[key].append(callback)

    def unsubscribe(
        self,
        register_name: str,
        field_name: str,
        callback: Callable[[Any], None],
    ) -> None:
        """Отписать callback от поля."""
        key = (register_name, field_name)
        try:
            self._field_observers[key].remove(callback)
        except ValueError:
            pass

    def subscribe_all(
        self,
        callback: Callable[[str, str, Any], None],
    ) -> None:
        """Подписать callback(register_name, field_name, value) на любое изменение."""
        if callback not in self._global_observers:
            self._global_observers.append(callback)

    def unsubscribe_all(self, callback: Callable[[str, str, Any], None]) -> None:
        """Отписать глобальный observer."""
        try:
            self._global_observers.remove(callback)
        except ValueError:
            pass

    def set_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> Tuple[bool, Optional[str]]:
        """Установить значение поля и уведомить подписчиков. При connection — вызвать send_callback."""
        reg = self.get_register(register_name)
        if reg is None:
            return False, f"Регистр '{register_name}' не найден"
        if not hasattr(reg, field_name):
            return False, f"Поле '{field_name}' не найдено в регистре '{register_name}'"
        is_valid, err = self.validate_field_value(register_name, field_name, value)
        if not is_valid:
            return False, err
        try:
            setattr(reg, field_name, value)
        except Exception as exc:
            return False, str(exc)
        self._notify_observers(register_name, field_name, value)
        if self._send_callback:
            targets = self._resolve_dispatch_targets(register_name, field_name, reg)
            if targets:
                snapshot = reg.model_dump() if hasattr(reg, "model_dump") else {}
                for channel in targets:
                    full_channel = (
                        f"control_{channel}" if not channel.startswith("control_") else channel
                    )
                    try:
                        self._send_callback(
                            full_channel, register_name, field_name, value, snapshot
                        )
                    except Exception:
                        pass
        return True, None

    def _resolve_dispatch_targets(
        self,
        register_name: str,
        field_name: str,
        reg: Any,
    ) -> List[str]:
        """
        Имена процессов для register_update.

        Приоритет: process_targets в FieldMeta.routing (Annotated) → в dict из get_field_metadata
        → register_dispatch класса → connection_map.
        """
        get_fm = getattr(type(reg), "get_field_meta", None)
        if callable(get_fm):
            fm = get_fm(field_name)
            if fm is not None and getattr(fm, "routing", None):
                raw_pt = (fm.routing or {}).get("process_targets")
                if raw_pt:
                    if isinstance(raw_pt, (list, tuple)):
                        return [str(x) for x in raw_pt if x is not None and str(x)]
                    return [str(raw_pt)]

        meta = self.get_field_metadata(register_name, field_name)
        routing = meta.get("routing") or {}
        raw_pt = routing.get("process_targets")
        if raw_pt:
            if isinstance(raw_pt, (list, tuple)):
                return [str(x) for x in raw_pt if x is not None and str(x)]
            return [str(raw_pt)]

        cls = type(reg)
        dispatch = getattr(cls, "register_dispatch", None)
        if dispatch is not None:
            targets = getattr(dispatch, "process_targets", None) or ()
            if targets:
                return [str(t) for t in targets]

        if register_name in self._connection_map:
            return [self._connection_map[register_name]]

        return []

    def notify_field_changed(
        self,
        register_name: str,
        field_name: str,
        value: Any,
    ) -> None:
        """Уведомить только field-подписчиков (без глобальных и send_callback)."""
        for cb in list(self._field_observers.get((register_name, field_name), [])):
            try:
                cb(value)
            except Exception:
                pass

    def _notify_observers(self, register_name: str, field_name: str, value: Any) -> None:
        """Уведомить field- и global-подписчиков."""
        for cb in list(self._field_observers.get((register_name, field_name), [])):
            try:
                cb(value)
            except Exception:
                pass
        for cb in list(self._global_observers):
            try:
                cb(register_name, field_name, value)
            except Exception:
                pass

    def register_names(self) -> List[str]:
        """Список имён зарегистрированных регистров."""
        return list(self._registers.keys())

    def set_register(self, name: str, instance: Any) -> None:
        """Установить экземпляр регистра (для динамического добавления/замены)."""
        self._registers[name] = instance

    def get_field_metadata(
        self,
        register_name: str,
        field_name: str,
        language: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Метаданные поля из json_schema_extra и model_fields.
        Включает routing: {router?, channel} для маршрутизации.
        """
        reg = self._registers.get(register_name)
        if reg is None:
            return {}
        field_info = getattr(reg, "model_fields", {}).get(field_name)
        if field_info is None:
            return {}
        extra = getattr(field_info, "json_schema_extra", None) or {}
        metadata = {
            "description": getattr(field_info, "description", "") or "",
            "info": extra.get("info", ""),
            "unit": extra.get("unit", ""),
            "range": extra.get("range", ""),
            "min": extra.get("min"),
            "max": extra.get("max"),
            "access_level": extra.get("access_level", 0),
            "examples": extra.get("examples", []),
            "default": getattr(field_info, "default", None),
            "readonly": extra.get("readonly", False),
            "hidden": extra.get("hidden", False),
            "transfer_k": extra.get("transfer_k", 1.0),
            "round_k": extra.get("round_k"),
        }
        if "routing" in extra:
            metadata["routing"] = dict(extra["routing"])
        for key in ("info_i18n", "description_i18n"):
            if key in extra:
                metadata[key] = extra[key]
        return metadata

    def validate_field_value(
        self,
        register_name: str,
        field_name: str,
        value: Any,
        current_access_level: int = 0,
    ) -> Tuple[bool, Optional[str]]:
        """Проверка значения по min/max и уровню доступа."""
        meta = self.get_field_metadata(register_name, field_name)
        if not meta:
            return False, f"Поле {register_name}.{field_name} не найдено"
        if meta.get("access_level", 0) > current_access_level:
            return False, f"Недостаточно прав доступа"
        if isinstance(value, (int, float)):
            min_val, max_val = meta.get("min"), meta.get("max")
            if min_val is not None and value < min_val:
                return False, f"Значение {value} меньше минимального {min_val}"
            if max_val is not None and value > max_val:
                return False, f"Значение {value} больше максимального {max_val}"
        return True, None

    def model_dump_all(self) -> Dict[str, Any]:
        """Экспорт всех регистров в словарь."""
        out: Dict[str, Any] = {}
        for name, reg in self._registers.items():
            if hasattr(reg, "model_dump"):
                out[name] = reg.model_dump()
            else:
                out[name] = dict(reg) if hasattr(reg, "__iter__") else {}
        return out

    def model_validate_all(self, data: Dict[str, Any], strict: bool = False) -> None:
        """Загрузить данные в регистры. Модели должны поддерживать model_validate (Pydantic v2)."""
        for name, reg in list(self._registers.items()):
            if name not in data:
                continue
            model_class = type(reg)
            if hasattr(model_class, "model_validate"):
                validated = model_class.model_validate(data[name], strict=strict)
                self._registers[name] = validated
