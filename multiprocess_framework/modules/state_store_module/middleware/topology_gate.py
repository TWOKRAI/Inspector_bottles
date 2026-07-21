# -*- coding: utf-8 -*-
"""topology_gate — гейт записей в ``processes.<name>.*`` по текущей топологии.

Purpose:
    Закрывает гонку воскрешения узла снятого процесса. При switch/cleanup PM
    удаляет поддерево ``processes.<name>`` (``_delete_process_state``), но
    сообщения ``state.set``/``state.merge``, отправленные УМИРАЮЩИМ инстансом
    до его смерти, доезжают до PM уже ПОСЛЕ удаления и создают узел заново —
    без ``pid`` и ``config``, из одних обрывков телеметрии (``plugins.*.io_peek``,
    ``workers.*``). Живьём (2026-07-21) после switch region→line в дереве так
    оставались 1-2 процесса старого рецепта, причём КАЖДЫЙ ПРОГОН РАЗНЫЕ —
    подпись гонки, а не невыполненного cleanup.

    Fencing-токены (ADR-PMM-014) эту дыру не закрывают ПО УСТРОЙСТВУ: они
    сравнивают incarnation отправителя, а incarnation растёт только при ЗАМЕНЕ
    инстанса. Снятый switch'ем процесс не заменён, а удалён — его incarnation
    никто не двигает, штамп совпадает с известным, билет проходит фильтр.
    Поэтому нужен отдельный критерий: не «свежий ли инстанс», а «существует ли
    вообще такой процесс в текущей топологии».

    Гейт — на записи (``before_set`` / ``before_merge``). Удаление НЕ гейтится:
    снос поддерева уже несуществующего процесса — это и есть штатная уборка,
    запрещать её нельзя.

Public API:
    - TopologyGateMiddleware — отклоняет записи для неизвестных процессов

Stability: lite
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .base import StateMiddleware

__all__ = ["TopologyGateMiddleware"]

#: Корень поддерева процессов в StateStore.
_ROOT = "processes"


class TopologyGateMiddleware(StateMiddleware):
    """Отклоняет запись в ``processes.<name>.*``, если ``<name>`` не в топологии.

    Знание «какие процессы существуют» принадлежит ProcessManager, поэтому оно
    приходит провайдером (тот же приём, что у fence-фильтра с
    ``get_expected_incarnation``) — модуль state_store не тянет зависимость на
    process_manager.

    Fail-open по трём границам, чтобы гейт не мог обрушить наблюдаемость:
      - путь вне ``processes.*`` — не наше дело, пропускаем;
      - запись в сам корень ``processes`` (без имени) — bootstrap дерева, пропускаем;
      - провайдер бросил исключение — пропускаем (гейт не важнее записи).

    Args:
        is_known: предикат ``name -> bool``; True, если процесс есть в топологии.
        on_reject: опциональный хук ``(path, name) -> None`` для счётчика/лога.
    """

    def __init__(
        self,
        is_known: Callable[[str], bool],
        *,
        on_reject: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self._is_known = is_known
        self._on_reject = on_reject

    @property
    def name(self) -> str:
        return "topology_gate"

    # ------------------------------------------------------------------
    # Внутреннее
    # ------------------------------------------------------------------

    def _process_name(self, path: str) -> Optional[str]:
        """Имя процесса из пути ``processes.<name>[...]`` или ``None``.

        ``None`` означает «путь не про конкретный процесс» — гейт не применяется.
        """
        if not isinstance(path, str):
            return None
        parts = path.split(".")
        if len(parts) < 2 or parts[0] != _ROOT:
            return None
        name = parts[1].strip()
        return name or None

    def _allowed(self, path: str, context: dict) -> bool:
        """True, если запись по ``path`` разрешена (см. границы fail-open).

        При отказе пишет в ``context`` конвенцию, которой уже следуют
        ``ThrottleMiddleware`` (``rejection_reason = "throttled"``) и
        ``ValidationMiddleware`` (``rejection_reason = "validation"``):
        ``rejection_reason = "topology_gate"`` + имя отклонённого процесса
        (``rejected_process``). Без этого ``state_store_manager.py`` отдаёт
        вызывающему безымянный fallback ``context.get("rejection_reason",
        "middleware")`` — причина отказа неразличима на вызывающей стороне.
        """
        name = self._process_name(path)
        if name is None:
            return True
        try:
            if self._is_known(name):
                return True
        except Exception:  # noqa: BLE001 — сбой провайдера не должен глушить запись
            return True
        context["rejection_reason"] = "topology_gate"
        context["rejected_process"] = name
        if self._on_reject is not None:
            try:
                self._on_reject(path, name)
            except Exception:  # noqa: BLE001 — счётчик/лог не роняет приём
                pass
        return False

    # ------------------------------------------------------------------
    # Хуки
    # ------------------------------------------------------------------

    def before_set(self, path: str, value: Any, source: str, context: dict) -> tuple[bool, Any]:
        return self._allowed(path, context), value

    def before_merge(self, path: str, data: dict, source: str, context: dict) -> tuple[bool, dict]:
        return self._allowed(path, context), data
