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


from multiprocess_framework.modules.logger_module import get_std_logger
from typing import Any, Callable, Dict, Optional

#: Команда брокера на оркестраторе (Task 5.11): «подпиши меня на хвост ВСЕХ».
SUBSCRIBE_ALL_COMMAND = "observability.tail.subscribe_all"

#: Адресат брокера. Имя оркестратора — то же, что у остальных команд GUI к PM.
BROKER_TARGET = "ProcessManager"

#: Сколько раз пробовать объявить намерение. Один выстрел, переживший отказ
#: транспорта, — это ноль выстрелов, а безлимитный повтор на каждой дельте
#: (их сотни в секунду) — шторм. Три попытки: отказ становится заметен по
#: журналу и при этом ограничен по построению.
MAX_ATTEMPTS = 3


class ObservabilityTailActivator:
    """Объявляет брокеру намерение «хочу весь хвост» — один раз за сессию."""

    def __init__(
        self,
        send_command: Callable[[str, str, Dict[str, Any]], Any],
        gui_name: str,
        *,
        log: Optional[Any] = None,
    ) -> None:
        """
        Args:
            send_command: отправка команды процессу (обычно CommandSender.send_command).
            gui_name: имя GUI-процесса — адрес-подписчик, на который идут записи.
            log: журнал для отказов — объект с ``.warning(str)``/``.error(str)``.
                По умолчанию логгер модуля; в живом GUI сюда подаётся адаптер к
                ``LoggerManager`` процесса, иначе строка ушла бы в голый
                ``logging`` — то есть в никуда (проектный долг Ф6).
        """
        self._send = send_command
        self._gui_name = gui_name
        self._log = log if log is not None else get_std_logger(__name__)
        self._announced = False
        self._attempts = 0

    @property
    def announced(self) -> bool:
        """Намерение объявлено брокеру и отправка не отказала (диагностика и тесты)."""
        return self._announced

    @property
    def attempts(self) -> int:
        """Сколько раз пробовали объявить (диагностика: >1 значит транспорт отказывал)."""
        return self._attempts

    def on_state_delta(self, msg_dict: Dict[str, Any]) -> None:
        """Слушатель state-дельт: на ПЕРВОЙ дельте ``processes.*`` объявить намерение.

        Дальнейшие дельты не разбираются: кто появился, кто перезапустился и кто
        пережил switch — забота брокера. GUI намеренно не знает состава системы.

        Отказ отправки НЕ проглатывается (находка 2 ревью 5.11): раньше пометка
        «объявлено» ставилась до отправки, а исключение уходило в ``except: pass`` —
        транспортный сбой на единственном выстреле оставлял GUI без хвоста навсегда
        и молча. Теперь отказ громкий и повторяется до ``MAX_ATTEMPTS``.
        """
        if self._announced or self._attempts >= MAX_ATTEMPTS:
            return
        if not isinstance(msg_dict, dict) or msg_dict.get("data_type") != "state_delta":
            return
        if not str(msg_dict.get("path") or "").startswith("processes."):
            return
        self._attempts += 1
        try:
            self._send(BROKER_TARGET, SUBSCRIBE_ALL_COMMAND, {"subscriber": self._gui_name})
        except Exception as exc:  # noqa: BLE001 — активация хвоста не рушит GUI
            last = self._attempts >= MAX_ATTEMPTS
            # Сообщение форматируется ЗДЕСЬ: приёмник журнала — либо logging-логгер,
            # либо адаптер к LoggerManager GUI-процесса (у него своя сигнатура).
            # Общий знаменатель — готовая строка, а не %-аргументы.
            message = (
                f"[observability] намерение подписки не объявлено брокеру "
                f"(попытка {self._attempts} из {MAX_ATTEMPTS}): {exc}"
                + (" — живого хвоста наблюдаемости не будет" if last else "")
            )
            (self._log.error if last else self._log.warning)(message)
            return
        self._announced = True
