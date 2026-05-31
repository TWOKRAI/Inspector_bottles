# -*- coding: utf-8 -*-
"""
Иерархическая адресация получателей внутри ``Message.targets``.

Контракт P0.2 плана ``transport-router-hub`` (см. memory ``project-hierarchical-addressing``).

Каждый элемент ``Message.targets`` — это **dotted-строка** иерархического адреса
``process[.worker[.…]]``. Почтовый принцип: Страна → Город → … → Человек.

Правила:
  - **Prefix-правило:** первый сегмент ВСЕГДА процесс и обязателен. Адресовать
    воркер в отрыве от процесса нельзя (форма dotted-строки это гарантирует —
    пустой первый сегмент ``.worker`` отвергается валидацией).
  - **Нижние уровни опциональны:** воркер и глубже можно не указывать.
  - **Backward-compat:** плоское имя ``"proc"`` (без точки) эквивалентно ``["proc"]`` —
    ровно как сегодня (``targets`` нигде ещё не dotted, см. recon #2).

Транспортная семантика (реализуется в P1/P2 — здесь ТОЛЬКО парсинг/валидация):
  - cross-process доставка идёт по ``process_of(target)`` (``address[0]``);
  - нижние уровни (``subpath_of(target)`` == ``address[1:]``) едут в билете и
    резолвятся ВНУТРИ процесса-получателя его Router/диспетчером, не плодя
    IPC-очереди.

Все функции — чистые (без побочных эффектов) и JSON-safe (правило #1 Dict-at-Boundary):
``list[str]`` сериализуется без потерь между процессами.
"""

from typing import Iterable, List, Optional, Union

from ..types import AddressValidationError

#: Разделитель уровней иерархического адреса.
SEPARATOR = "."

#: Спец-адреса широковещания. НЕ являются иерархическими — обрабатываются
#: отдельным fan-out путём (см. recon #6); валидация dotted-формы к ним не применяется.
BROADCAST_TARGETS = frozenset({"all", "broadcast"})


def is_broadcast(target: str) -> bool:
    """``True``, если ``target`` — спец-адрес широковещания (``"all"``/``"broadcast"``)."""
    return target in BROADCAST_TARGETS


def validate_address(target: str) -> None:
    """Проверить корректность иерархического адреса.

    Raises:
        AddressValidationError: если адрес — не строка, пустой, или содержит
            пустой сегмент (``".worker"`` — воркер без процесса; ``"proc."`` —
            висячая точка; ``"a..b"`` — пропущенный уровень).
    """
    if not isinstance(target, str) or not target:
        raise AddressValidationError(f"Адрес должен быть непустой строкой, получено: {target!r}")
    if is_broadcast(target):
        return
    if any(not segment for segment in target.split(SEPARATOR)):
        raise AddressValidationError(
            f"Адрес {target!r} содержит пустой сегмент (воркер без процесса / лишняя точка нарушают prefix-правило)"
        )


def split_address(target: str) -> List[str]:
    """Разобрать dotted-адрес в список уровней ``[process, worker, …]``.

    ``"proc"`` → ``["proc"]`` (backward-compat); ``"proc.worker"`` → ``["proc", "worker"]``.
    Спец-адреса широковещания возвращаются как одноэлементный список.

    Raises:
        AddressValidationError: при невалидном адресе (см. :func:`validate_address`).
    """
    validate_address(target)
    if is_broadcast(target):
        return [target]
    return target.split(SEPARATOR)


def process_of(target: str) -> str:
    """Процесс-получатель — ``address[0]``. Уровень cross-process доставки."""
    return split_address(target)[0]


def worker_of(target: str) -> Optional[str]:
    """Воркер-получатель — ``address[1]`` или ``None``, если адрес — только процесс."""
    parts = split_address(target)
    return parts[1] if len(parts) > 1 else None


def subpath_of(target: str) -> List[str]:
    """Нижние уровни адреса (``address[1:]``) — воркер и глубже.

    Эти уровни резолвятся ВНУТРИ процесса-получателя (P2), не на транспорте.
    """
    return split_address(target)[1:]


def depth(target: str) -> int:
    """Число уровней в адресе (1 — только процесс, 2 — процесс+воркер, …)."""
    return len(split_address(target))


def join_address(parts: Iterable[str]) -> str:
    """Собрать иерархический адрес из уровней: ``["proc", "worker"]`` → ``"proc.worker"``.

    Raises:
        AddressValidationError: если уровней нет, или какой-то пуст.
    """
    parts = list(parts)
    if not parts or any(not p for p in parts):
        raise AddressValidationError(f"Нельзя собрать адрес из {parts!r}: список пуст или содержит пустой уровень")
    return SEPARATOR.join(parts)


def normalize_targets(
    targets: Union[str, Iterable[str], None] = None,
    target: Optional[str] = None,
) -> List[str]:
    """Свести оба способа адресации к единому ``targets: list[str]`` (recon #2).

    Сегодня сосуществуют скалярное ``target`` (data-plane: ``send_to_process``) и
    списочное ``targets`` (CommandSender/StateProxy/DeltaDispatcher). Эта функция
    принимает оба, отдаёт плоский список без дублей с сохранением порядка.
    Целевой контракт — ``targets: list[str]``; ``target`` остаётся входным
    backward-shim до завершения миграции отправителей (P4).
    """
    out: List[str] = []
    if targets:
        if isinstance(targets, str):
            out.append(targets)
        else:
            out.extend(targets)
    if target and target not in out:
        out.append(target)
    return out
