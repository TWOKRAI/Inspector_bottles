# -*- coding: utf-8 -*-
"""registers.py — RegisterOps: аппарат живой записи регистров как отдельный класс.

Владелец состояния регистрового контура: verify-probe (write → readback → diff),
snapshot/restore (гарантированный откат эксперимента) и commit-confirmed запись
(армированный таймер восстановит pre-image, если запись не подтверждена — клиентский
предохранитель по аналогии с Juniper ``commit confirmed``).

Раньше жил ~4 полями и десятком методов внутри BackendDriver — теперь ВЛАДЕЕТ своим
состоянием (`_pending_commits`, счётчик commit_id, журнал откатов) и инъектируется в
driver (`self._registers = RegisterOps(self)`), а driver-обёртки лишь делегируют.
Команды к бэкенду идут через back-ref на driver (`self._drv`): send_command,
introspect_registers, introspect_capabilities, _looks_failed. Армированные таймеры
снимаются в :meth:`stop`, которую зовёт ``BackendDriver.close()`` (driver уходит —
откатывать по мёртвому сокету нечем).
"""

from __future__ import annotations

import copy
import itertools
import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .protocol import _find_payload

# Логгер того же семейства, что и driver: авто-откат бьёт в фоновом (daemon) потоке
# таймера, его провал иначе был бы невидим (синхронного возврата агенту нет).
_log = logging.getLogger("backend_ctl.driver")


@dataclass
class _PendingCommit:
    """Ожидающая подтверждения запись регистра (commit-confirmed).

    Клиентский предохранитель по аналогии с Juniper ``commit confirmed``: пока не
    вызван :meth:`RegisterOps.register_confirm`, армированный таймер восстановит
    ``pre_value`` (или снимет запись, если поля до записи не было). ``had_field``
    отличает «поле существовало, откатываем к прежнему значению» от «поля не было —
    откатывать нечего, только разоружить».
    """

    commit_id: str
    process: str
    register: str
    field: str
    pre_value: Any
    had_field: bool
    timer: "threading.Timer"


class RegisterOps:
    """Владелец регистрового контура; команды идут через back-ref на driver."""

    def __init__(self, driver: Any) -> None:
        self._drv = driver
        # commit-confirmed регистры: армированные, но ещё не подтверждённые записи.
        # Каждая держит threading.Timer, который восстановит pre-image, если
        # register_confirm() не вызван за confirm_within сек. Таймеры снимаются в
        # stop() (driver уходит → откатывать по мёртвому сокету нечем).
        self._pending_commits: Dict[str, _PendingCommit] = {}
        self._pending_commits_lock = threading.Lock()
        self._commit_counter = itertools.count(1)
        # Исходы авто-откатов: таймер бьёт в фоновом потоке, синхронного возврата
        # агенту нет — фиксируем результат каждого срабатывания сюда (ограниченное
        # кольцо), чтобы register_confirm/register_rollback_log могли ответить «что
        # случилось с этим commit_id». Под _pending_commits_lock.
        self._rollback_journal: "deque[Dict[str, Any]]" = deque(maxlen=64)

    def _read_registers(self, process: str, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Регистры процесса как ``{register: {field: value}}`` (один readback-хелпер).

        Общий разбор ответа ``introspect.registers`` (снимает конверт ``{success,
        result: …}`` через ``_find_payload``) для verify-probe, snapshot и restore —
        чтобы форма ответа парсилась в одном месте.
        """
        res = self._drv.introspect_registers(process, timeout=timeout)
        payload = _find_payload(res, "registers")
        registers = payload.get("registers") if isinstance(payload, dict) else None
        return registers if isinstance(registers, dict) else {}

    def _topology_process_names(
        self,
        *,
        pm_name: str = "ProcessManager",
        timeout: Optional[float] = None,
    ) -> List[str]:
        """Список процессов системы одним запросом карточки PM (без fan-out).

        Берёт только ``processes``-топологию из ``introspect.capabilities`` PM — не
        зовёт ``capabilities`` (та вдобавок опрашивает карточку КАЖДОГО процесса,
        что для перечисления имён избыточно). Возвращает PM + детей.
        """
        pm_res = self._drv.introspect_capabilities(pm_name, timeout=timeout)
        payload = _find_payload(pm_res, "processes", "commands")
        topology = payload.get("processes") if isinstance(payload, dict) else None
        children = sorted(topology) if isinstance(topology, dict) else []
        return [pm_name, *children]

    def set_register(
        self,
        process: str,
        register: str,
        field: str,
        value: Any,
        *,
        confirm_within: Optional[float] = None,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Записать значение регистра в живой процесс (live field-write).

        Ключи data — канонический контракт ``register_update`` (тот же, что шлёт GUI
        через routing_map/CommandSender): ``{"register", "field", "value"}``.
        Исторический баг: driver слал ``plugin_name`` — обработчик оркестратора молча
        выходил, запись была no-op (найдено verify-probe). Имя регистра обычно
        совпадает с plugin_name (регистр на плагин).

        ``confirm_within=N`` переводит запись в режим *commit-confirmed*: перед
        записью снимается pre-image поля, а после — readback-подтверждение (иначе
        молчаливый no-op не вооружает таймер) и армируется таймер, который через ``N``
        секунд восстановит прежнее значение, если не вызван :meth:`register_confirm` с
        вернувшимся ``commit_id``. Аналог Juniper ``commit confirmed`` — безопасный
        эксперимент с гарантированным откатом. **Ограничение:** предохранитель живёт
        только в пределах этой driver-сессии — ``close()``/реконнект снимает таймер, и
        неподтверждённая запись остаётся применённой (ответ несёт ``session_scoped``).
        """
        if confirm_within is not None:
            return self._set_register_confirmed(process, register, field, value, float(confirm_within), **kw)
        return self._drv.send_command(
            process,
            "register_update",
            {"register": register, "field": field, "value": value},
            **kw,
        )

    def set_register_verified(
        self,
        process: str,
        register: str,
        field: str,
        value: Any,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Verify-probe: write → readback → diff.

        Не доверяет ack'у записи: после :meth:`set_register` читает
        ``introspect.registers`` того же процесса и сравнивает фактическое значение
        поля с ожидаемым. Ловит весь класс молчаливых no-op'ов: несуществующий
        регистр/поле, неверные ключи payload, отвал приёмника. ``verified`` может
        отличаться от ``value`` и при легитимной коэрции значения Pydantic-схемой —
        тогда смотреть ``actual``.
        """
        ack = self.set_register(process, register, field, value, timeout=timeout)
        registers = self._read_registers(process, timeout=timeout)
        reg = registers.get(register)
        found = isinstance(reg, dict) and field in reg
        actual = reg.get(field) if found else None
        verified = bool(found and actual == value)
        return {
            "success": verified,
            "verified": verified,
            "found": found,
            "process": process,
            "register": register,
            "field": field,
            "expected": value,
            "actual": actual,
            "known_registers": sorted(registers),
            "ack": ack,
        }

    # ---- Snapshot / restore регистров: гарантированный откат эксперимента ----

    def register_snapshot(
        self,
        process: Optional[str] = None,
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Снять снимок регистров для последующего :meth:`register_restore`.

        ``process`` задан — снимок одного процесса; опущен — снимок всех процессов
        системы (топология одним запросом карточки PM, без per-process fan-out).
        Форма всегда единообразна::

            {"processes": {proc: {register: {field: value}}}}

        Значения — глубокие копии (отвязаны от живого read-model), поэтому снимок
        переживает последующие правки. Аналог NETCONF candidate-config / running snapshot.
        """
        if process is not None:
            targets = [process]
        else:
            targets = self._topology_process_names(timeout=timeout)
        processes: Dict[str, Dict[str, Any]] = {}
        for name in targets:
            registers = self._read_registers(name, timeout=timeout)
            processes[name] = {
                reg: copy.deepcopy(fields) for reg, fields in registers.items() if isinstance(fields, dict)
            }
        return {"processes": processes}

    def register_restore(
        self,
        snapshot: Dict[str, Any],
        *,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Восстановить регистры из снимка :meth:`register_snapshot`.

        Для каждого процесса: readback → пишет ТОЛЬКО дрейфнувшие поля (уже-верные и
        неизменившиеся read-only не трогаются — меньше лишних write и меньше шума от
        полей, которые всё равно совпадают), затем сверяет свежим readback'ом. Не
        доверяет ack'ам записи (как verify-probe). Возвращает ``success`` (все поля
        снимка совпали), ``written`` (реально изменённые), ``skipped`` (уже верные),
        ``verified`` (доведённые до снимка) и ``mismatches``.

        Замечание: поля с живым/вычисляемым значением (счётчики, timestamps), успевшие
        измениться после снимка, попадут в ``mismatches`` — их «восстановить» нельзя, и
        это честный сигнал, а не сбой самого restore.
        """
        processes = snapshot.get("processes") if isinstance(snapshot, dict) else None
        if not isinstance(processes, dict):
            return {"success": False, "error": "снимок без ключа 'processes' (ожидается форма register_snapshot)"}

        written = 0
        total = 0
        mismatches: List[Dict[str, Any]] = []
        for proc, registers in processes.items():
            if not isinstance(registers, dict):
                continue
            current = self._read_registers(proc, timeout=timeout)  # readback ДО записи
            wrote_this_proc = False
            for reg, fields in registers.items():
                if not isinstance(fields, dict):
                    continue
                creg = current.get(reg)
                for field, value in fields.items():
                    total += 1
                    cur = creg.get(field) if isinstance(creg, dict) else None
                    if cur != value:  # пишем только то, что дрейфнуло
                        self.set_register(proc, reg, field, value, timeout=timeout)
                        written += 1
                        wrote_this_proc = True

            # Verify: свежий readback только если что-то писали (иначе current актуален).
            verify_src = self._read_registers(proc, timeout=timeout) if wrote_this_proc else current
            for reg, fields in registers.items():
                if not isinstance(fields, dict):
                    continue
                vreg = verify_src.get(reg)
                for field, value in fields.items():
                    got = vreg.get(field) if isinstance(vreg, dict) else None
                    if got != value:
                        mismatches.append(
                            {"process": proc, "register": reg, "field": field, "expected": value, "actual": got}
                        )
        return {
            "success": not mismatches,
            "written": written,
            "skipped": total - written,
            "verified": total - len(mismatches),
            "mismatches": mismatches,
        }

    # ---- commit-confirmed запись регистра: авто-откат без подтверждения ----

    def _set_register_confirmed(
        self,
        process: str,
        register: str,
        field: str,
        value: Any,
        confirm_within: float,
        **kw: Any,
    ) -> Dict[str, Any]:
        """Ядро режима ``set_register(confirm_within=N)`` — см. :meth:`set_register`."""
        # pre-image ДО записи: к нему откатимся, если поле уже существовало.
        registers = self._read_registers(process, timeout=kw.get("timeout"))
        reg = registers.get(register)
        had_field = isinstance(reg, dict) and field in reg
        pre_value = copy.deepcopy(reg[field]) if had_field else None

        ack = self._drv.send_command(
            process,
            "register_update",
            {"register": register, "field": field, "value": value},
            **kw,
        )
        if self._drv._looks_failed(ack):
            # Запись явно провалилась — таймер отката не армируем (откатывать нечего).
            return {
                "success": False,
                "pending": False,
                "error": "запись регистра провалилась — commit-confirmed не вооружён",
                "process": process,
                "register": register,
                "field": field,
                "ack": ack,
            }

        # Readback-подтверждение ДО арминга (не доверяем ack'у, как verify-probe):
        # если поля нет в снимке после записи — это молчаливый no-op (опечатка в имени
        # регистра/поля, отвал приёмника). Армировать таймер отката тогда — ложная
        # уверенность: откатывать нечего, а агент верит, что вооружён. Значение может
        # НЕ совпасть с value при легитимной Pydantic-коэрции — тогда verified=False,
        # но поле есть → запись применилась, откат к pre_value корректен.
        post = self._read_registers(process, timeout=kw.get("timeout"))
        preg = post.get(register)
        field_present = isinstance(preg, dict) and field in preg
        actual = preg.get(field) if field_present else None
        if not field_present:
            return {
                "success": False,
                "pending": False,
                "verified": False,
                "error": "запись не подтверждена readback'ом (нет регистра/поля?) — commit-confirmed не вооружён",
                "process": process,
                "register": register,
                "field": field,
                "expected": value,
                "actual": actual,
                "had_field": had_field,
                "ack": ack,
            }

        commit_id = f"{process}:{register}.{field}#{next(self._commit_counter)}"
        timer = threading.Timer(confirm_within, self._auto_rollback, args=(commit_id,))
        timer.daemon = True
        pc = _PendingCommit(commit_id, process, register, field, pre_value, had_field, timer)
        with self._pending_commits_lock:
            self._pending_commits[commit_id] = pc
        timer.start()
        return {
            "success": True,
            "pending": True,
            "verified": actual == value,
            "commit_id": commit_id,
            "process": process,
            "register": register,
            "field": field,
            "value": value,
            "actual": actual,
            "pre_value": pre_value,
            "had_field": had_field,
            "confirm_within": confirm_within,
            # Предохранитель живёт только в пределах ЭТОЙ driver-сессии: close()/реконнект
            # (DriverSession.reset) снимает таймер, и неподтверждённая запись остаётся
            # применённой. Не полагаться на авто-откат через границу реконнекта.
            "session_scoped": True,
            "ack": ack,
        }

    def register_confirm(self, commit_id: str) -> Dict[str, Any]:
        """Подтвердить commit-confirmed запись: снять таймер авто-отката.

        После подтверждения значение остаётся навсегда. Если ``commit_id`` неизвестен —
        ``success=False`` со списком ещё ожидающих ``known``; если он уже откатился по
        таймауту, из журнала подставляется ``rolled_back`` (исход отката), чтобы
        «опоздавший» confirm не гадал, что случилось.
        """
        with self._pending_commits_lock:
            pc = self._pending_commits.pop(commit_id, None)
            known = sorted(self._pending_commits)
            prior = None
            if pc is None:
                prior = next((e for e in reversed(self._rollback_journal) if e["commit_id"] == commit_id), None)
        if pc is None:
            res = {
                "success": False,
                "commit_id": commit_id,
                "error": "нет ожидающего commit-confirmed (уже подтверждён, откачен или неизвестен)",
                "known": known,
            }
            if prior is not None:
                res["rolled_back"] = prior  # уже откатился по таймауту — вот исход
            return res
        pc.timer.cancel()
        return {
            "success": True,
            "commit_id": commit_id,
            "confirmed": True,
            "process": pc.process,
            "register": pc.register,
            "field": pc.field,
        }

    def _auto_rollback(self, commit_id: str) -> None:
        """Callback таймера: восстановить pre-image, если запись не подтверждена.

        Атомарный ``pop`` под локом — арбитр гонки с :meth:`register_confirm`: кто
        первым забрал запись, тот и действует (второй увидит ``None`` и выйдет). Исход
        (ok/failed/noop) пишется в журнал — иначе провал отката в фоновом потоке был бы
        невидим агенту (он вызывал в расчёте на откат). Проверяем и ack (обрыв/таймаут
        возвращают error-dict, а не исключение), и исключение.
        """
        with self._pending_commits_lock:
            pc = self._pending_commits.pop(commit_id, None)
        if pc is None:
            return
        if not pc.had_field:
            # Поля до записи не существовало — откатывать нечего, только разоружаем.
            self._record_rollback(pc, "noop")
            return
        try:
            ack = self.set_register(pc.process, pc.register, pc.field, pc.pre_value)
        except Exception as exc:  # noqa: BLE001 — таймер в daemon-потоке, исключение иначе теряется
            _log.exception("commit-confirmed авто-откат %s не удался", commit_id)
            self._record_rollback(pc, "failed", error=str(exc))
            return
        if self._drv._looks_failed(ack):
            _log.warning("commit-confirmed авто-откат %s: запись отклонена бэкендом (%s)", commit_id, ack)
            self._record_rollback(pc, "failed", error=ack)
        else:
            self._record_rollback(pc, "ok")

    def _record_rollback(self, pc: _PendingCommit, outcome: str, *, error: Any = None) -> None:
        """Зафиксировать исход авто-отката в кольце журнала (под локом)."""
        entry: Dict[str, Any] = {
            "commit_id": pc.commit_id,
            "process": pc.process,
            "register": pc.register,
            "field": pc.field,
            "outcome": outcome,
        }
        if error is not None:
            entry["error"] = error
        with self._pending_commits_lock:
            self._rollback_journal.append(entry)

    def register_rollback_log(self, *, limit: Optional[int] = None) -> Dict[str, Any]:
        """Журнал исходов авто-откатов этой driver-сессии (новейшие последними).

        Позволяет агенту, армировавшему commit-confirmed и не подтвердившему его,
        узнать, ЧЕМ закончился откат: ``outcome`` = ``ok`` / ``failed`` (+``error``) /
        ``noop`` (поля не было, откатывать нечего). Кольцо на 64 записи.
        """
        with self._pending_commits_lock:
            entries = list(self._rollback_journal)
        if limit is not None:
            # limit>0 → последние N; limit==0 → пусто («последние 0 записей»);
            # limit<0 (бессмыслица) → пусто. Нельзя entries[-limit:]: при limit==0
            # это entries[0:], то есть ВЕСЬ журнал вместо пустого (зеркало контракта
            # telemetry_history — там та же ловушка falsy-slice уже закрыта).
            entries = entries[-limit:] if limit > 0 else []
        return {"success": True, "entries": entries}

    def stop(self) -> None:
        """Снять все армированные таймеры отката (вызывается из ``BackendDriver.close()``).

        Driver уходит — откатывать по закрывающемуся сокету нечем (и не нужно: авто-
        откат это клиентский предохранитель на время жизни сессии). Неподтверждённые
        записи остаются применёнными; таймеры снимаются, чтобы не бить по мёртвому сокету.
        """
        with self._pending_commits_lock:
            pcs = list(self._pending_commits.values())
            self._pending_commits.clear()
        for pc in pcs:
            pc.timer.cancel()


__all__ = ["RegisterOps", "_PendingCommit"]
