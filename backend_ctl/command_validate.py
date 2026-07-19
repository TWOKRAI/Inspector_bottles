# -*- coding: utf-8 -*-
"""command_validate.py — клиентская валидация send_command по схеме (E.2, Phase E).

``send_command`` — escape-hatch «открытого мира»: неверный target/команда/неполные
аргументы уходили на бэкенд и возвращались ТАЙМАУТОМ (агент гадал, что не так).
Здесь — предполётная сверка ``args`` со схемой из capabilities-кэша сессии: ошибка
УЧИТ («поле X обязательно, схема: …») ещё до отправки.

Консервативно по замыслу — валидатор помогает, а не запрещает:
  * неизвестный процесс (target) → блок: команду некуда маршрутизировать;
  * известный процесс, у команды есть ``params_schema`` → проверка обязательных полей;
  * команда не заявлена в capabilities ИЛИ без схемы → ПРОПУСК (карточка может быть
    неполной — не блокируем легитимный динамический вызов).

Чистая функция над ``Capabilities`` (никакого IPC): кэш и refresh-политику держит
сессия, схему знает эта функция.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _find_command(commands: Any, name: str) -> Optional[Dict[str, Any]]:
    """Найти карточку команды по имени в списке ``commands`` карточки процесса."""
    if not isinstance(commands, list):
        return None
    for cmd in commands:
        if isinstance(cmd, dict) and cmd.get("name") == name:
            return cmd
    return None


def _required_missing(schema: Any, args: Dict[str, Any]) -> List[str]:
    """Имена обязательных полей схемы (v1: {name,type,required}), отсутствующих в args."""
    missing: List[str] = []
    for field in schema:
        if not isinstance(field, dict) or not field.get("required"):
            continue
        fname = field.get("name")
        if fname is not None and fname not in args:
            missing.append(str(fname))
    return missing


def target_unknown(caps: Any, target: str) -> bool:
    """Отсутствует ли процесс-адресат в своде (повод обновить кэш — мог быть hot-added)."""
    processes = getattr(caps, "processes", None)
    return isinstance(processes, dict) and target not in processes


def validate_command_args(caps: Any, target: str, command: str, args: Any) -> Optional[str]:
    """Проверить send_command по схеме свода. ``None`` — ок; строка — обучающая ошибка.

    Args:
        caps: объект :class:`~backend_ctl.protocol.Capabilities` (свод) или совместимый.
        target: имя процесса-адресата.
        command: имя команды.
        args: словарь аргументов команды (``data``), может быть None.
    """
    processes = getattr(caps, "processes", None)
    if not isinstance(processes, dict):
        return None  # свод недоступен/неполон — не мешаем (валидатор — помощник, не гейт)

    proc = processes.get(target)
    if proc is None:
        # Блокируем «нет такого адресата» ТОЛЬКО по здоровому своду (ok): при деградации
        # (какая-то карточка не собралась) processes неполон — не ложно-блокируем легитимный
        # вызов. Свод здоров + адресата нет → почти наверняка опечатка, учим до таймаута.
        if not getattr(caps, "ok", False):
            return None
        available = ", ".join(sorted(processes)) or "(свод пуст)"
        return (
            f"процесс {target!r} не найден среди адресатов: {available}. "
            "Проверь имя процесса (capabilities) или обнови топологию."
        )

    cmd = _find_command(getattr(proc, "commands", None), command)
    if cmd is None:
        return None  # команда не заявлена в карточке — карточка может быть неполной, пропускаем

    schema = cmd.get("params_schema")
    if not isinstance(schema, list):
        return None  # нет схемы для сверки — нечего утверждать

    missing = _required_missing(schema, args if isinstance(args, dict) else {})
    if missing:
        return (
            f"команде {command!r} процесса {target!r} не хватает обязательных полей: "
            f"{', '.join(missing)}. Схема параметров: {schema}"
        )
    return None


__all__ = ["validate_command_args", "target_unknown"]
