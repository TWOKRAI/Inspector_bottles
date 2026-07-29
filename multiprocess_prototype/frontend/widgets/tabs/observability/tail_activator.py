# -*- coding: utf-8 -*-
"""
ObservabilityTailActivator — включение live-хвоста наблюдаемости ОДНИМ вызовом.

Форвардер на каждом backend-процессе «мёртв» без подписчика (как log_tail), но
кто именно живёт в системе прямо сейчас — знает оркестратор, а не GUI. До
Task 5.11 GUI выяснял это сам: ловил дельты ``processes.*``, дедуплицировал по
имени и переподписывался по ``supervisor.event="recovered"``. Цена этого была
записана прямо здесь резидуалом F4 — ручной ``process.restart`` и hot-swap
события ``recovered`` не публикуют, поэтому новая инкарнация оставалась без
хвоста, и GUI об этом молчал.

Task 5.11 переносит логику туда, где есть сигнал: **брокер подписки на
оркестраторе**. GUI объявляет намерение один раз, PM разворачивает его на все
живые процессы и сам доигрывает каждой свежей инкарнации — включая ручной
рестарт и пересозданные switch'ем. Резидуал F4 закрыт не заплаткой на второй
триггер, а тем, что триггер стал не нужен.

Почему намерение всё ещё отправляется по state-дельте, а не сразу на старте GUI:
дельта ``processes.*`` — первое доказательство, что оркестратор поднялся и
отвечает. Команда, посланная раньше, ушла бы в пустоту молча. Это ОДИН выстрел,
а не цикл: имена процессов больше не разбираются вовсе.

Qt-free: принимает callable ``send_command(target, command, args)`` — тестируется
без живого backend.
"""

from __future__ import annotations

from typing import Any, Callable, Dict

#: Команда брокера на оркестраторе (Task 5.11): «подпиши меня на хвост ВСЕХ».
SUBSCRIBE_ALL_COMMAND = "observability.tail.subscribe_all"

#: Адресат брокера. Имя оркестратора — то же, что у остальных команд GUI к PM.
BROKER_TARGET = "ProcessManager"


class ObservabilityTailActivator:
    """Объявляет брокеру намерение «хочу весь хвост» — ровно один раз за сессию."""

    def __init__(self, send_command: Callable[[str, str, Dict[str, Any]], Any], gui_name: str) -> None:
        """
        Args:
            send_command: отправка команды процессу (обычно CommandSender.send_command).
            gui_name: имя GUI-процесса — адрес-подписчик, на который идут записи.
        """
        self._send = send_command
        self._gui_name = gui_name
        self._announced = False

    @property
    def announced(self) -> bool:
        """Намерение уже объявлено брокеру (диагностика и тесты)."""
        return self._announced

    def on_state_delta(self, msg_dict: Dict[str, Any]) -> None:
        """Слушатель state-дельт: на ПЕРВОЙ дельте ``processes.*`` объявить намерение.

        Дальнейшие дельты не разбираются: кто появился, кто перезапустился и кто
        пережил switch — забота брокера. GUI намеренно не знает состава системы.
        """
        if self._announced:
            return
        if not isinstance(msg_dict, dict) or msg_dict.get("data_type") != "state_delta":
            return
        if not str(msg_dict.get("path") or "").startswith("processes."):
            return
        # Пометка ДО отправки: сбой транспорта не имеет права превратить один
        # выстрел в цикл повторов на каждой дельте (их сотни в секунду).
        self._announced = True
        try:
            self._send(BROKER_TARGET, SUBSCRIBE_ALL_COMMAND, {"subscriber": self._gui_name})
        except Exception:  # noqa: BLE001 — активация хвоста best-effort, не рушим GUI
            pass
