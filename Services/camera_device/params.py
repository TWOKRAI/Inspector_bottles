# -*- coding: utf-8 -*-
"""План записи профиля камеры из register'а и таблицы привязки (Task 1.6).

Чистая логика, без потоков и SDK. Из полей register-класса (`FieldMeta.enabled_if`, `ui_group`)
и таблицы `BINDINGS` драйвера (`имя поля register'а -> Binding`) строится упорядоченный список шагов
записи; пропуск шага — данные (`Step.skip`), а не исключение: причина уходит в лог сеанса (Task 2.2).

Правила:
  * порядок шагов — порядок полей класса (`model_fields`: родитель раньше потомка);
  * «не управлять группой» — только флаг `<группа>_managed` (Р5): флаг группы `False` или не задан ->
    ни одного шага группы; `0` и `""` — обычные значения, а не «не задано»;
  * поле с ложным `enabled_if` -> шаг с `skip="не нужен: <родитель>=<значение>"`; если родитель сам
    пропущен, потомок наследует причину родителя (условие по значению пропущенного родителя не считается);
  * тексты ошибок называют имена полей и ключей, но не значения из рецепта.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from multiprocess_framework.modules.data_schema_module import FieldMeta

from .interface import Binding

MANAGED_SUFFIX = "_managed"
NOT_SET = "<не задано>"


@dataclass(frozen=True)
class Step:
    """Один шаг плана: поле register'а, его привязка, значение и причина пропуска (`None` — писать)."""

    field: str
    binding: Binding
    value: Any
    skip: str | None = None


def _is_flag(name: str) -> bool:
    return name.endswith(MANAGED_SUFFIX)


def _unmanaged_fields(fields: Mapping[str, FieldMeta], values: Mapping[str, Any]) -> set[str]:
    """Поля групп, у которых флаг `*_managed` ложен или не задан в `values`."""
    off_groups = {
        meta.ui_group
        for name, meta in fields.items()
        if _is_flag(name) and meta.ui_group is not None and not values.get(name, False)
    }
    return {name for name, meta in fields.items() if not _is_flag(name) and meta.ui_group in off_groups}


def _skip_reason(meta: FieldMeta, values: Mapping[str, Any], skipped: Mapping[str, str]) -> str | None:
    """Причина пропуска поля по `enabled_if`; `None` — поле нужно."""
    if meta.enabled_if is None:
        return None
    for parent, allowed in meta.enabled_if.items():
        if skipped.get(parent):
            return skipped[parent]
        if parent not in values:
            return f"не нужен: {parent}={NOT_SET}"
        if values[parent] not in allowed:
            return f"не нужен: {parent}={values[parent]}"
    return None


def build_plan(register_cls: type, values: Mapping[str, Any], bindings: Mapping[str, Binding]) -> list[Step]:
    """Упорядоченный план записи профиля: шаги для полей, у которых есть привязка в `bindings`.

    Raises:
        ValueError: у нужного (не пропущенного) поля нет значения в `values`; текст называет поле.
    """
    fields: Mapping[str, FieldMeta] = register_cls.get_all_fields_meta()  # type: ignore[attr-defined]
    off = _unmanaged_fields(fields, values)
    skipped: dict[str, str] = {}  # имя -> причина пропуска
    plan: list[Step] = []
    for name, meta in fields.items():
        if name in off:
            skipped[name] = "не нужен: группа не управляется"
            continue
        reason = _skip_reason(meta, values, skipped)
        if reason is not None:
            skipped[name] = reason
        binding = bindings.get(name)
        if binding is None:
            continue
        if reason is None and name not in values:
            raise ValueError(f"нет значения для поля {name}")
        plan.append(Step(field=name, binding=binding, value=values.get(name), skip=reason))
    return plan


def check_bindings(register_cls: type, bindings: Mapping[str, Binding], vendor_fields: Collection[str]) -> None:
    """Сверить ключи таблицы привязки с полями register'а.

    Ожидаемые ключи — поля register'а с `FieldMeta`, кроме флагов `*_managed` (переключатели групп,
    не параметры прибора) и `vendor_fields` (поля, которые вендор обслуживает мимо таблицы).

    Raises:
        ValueError: лишний или недостающий ключ; текст называет ключи и не содержит значений.
    """
    fields = register_cls.get_all_fields_meta()  # type: ignore[attr-defined]
    expected = {name for name in fields if not _is_flag(name)} - set(vendor_fields)
    extra = sorted(set(bindings) - expected)
    missing = sorted(expected - set(bindings))
    problems = []
    if extra:
        problems.append(f"лишние ключи привязки: {', '.join(extra)}")
    if missing:
        problems.append(f"нет привязки для полей: {', '.join(missing)}")
    if problems:
        raise ValueError("; ".join(problems))
