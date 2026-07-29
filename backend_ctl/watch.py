# -*- coding: utf-8 -*-
"""watch.py — WatchController: GUI-эквивалентный watch-профиль как отдельный класс.

Приёмный профиль GUI одной командой: ``state.subscribe`` по wildcard'ам +
хвост наблюдаемости со ВСЕХ процессов. Владеет своим состоянием и инъектируется
в driver (``self._watch = WatchController(self)``), а driver-обёртки делегируют.

**Task 5.11.h — контур переподписки снят.** Здесь жила собственная машина:
слушатель supervisor-события ``recovered`` в reader-потоке, очередь намерений,
applier-поток, дедуп по именам и само-исцеление in-flight resub'а. Всю эту работу
делает брокер подписки на оркестраторе (Task 5.11): драйвер говорит «хочу всё»
ОДИН раз, а разворачивает намерение и переподписывает свежие инкарнации тот, у
кого есть сигнал «поднялась новая», — PM.

Что это чинит, помимо объёма:

* триггером переподписки было supervisor-событие ``recovered``, которое НЕ
  публикуется на ручном рестарте и на switch рецепта — драйвер молча оставался
  без хвоста от новых инкарнаций (та же дыра, что была у GUI и закрыта 5.11);
* старт watch стоил N последовательных round-trip'ов (по одному на процесс,
  таймаут до 5с каждый) — стал один;
* applier-поток был обходным манёвром вокруг дедлока «request() из reader-потока».
  Конструкции нет — нет и класса дефектов.

Записи как шли адресным пушем напрямую драйверу, так и идут: PM брокер, не транзит.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional

# GUI-эквивалентный набор wildcard'ов state-подписки (Task 2.2): зеркало
# multiprocess_prototype/frontend/process.py — ровно то, на что подписан GUI.
# Прототип может передать свой набор в watch_like_gui(patterns=...).
# F7 (framework-first): ``devices.**``/``calibration.**`` — app-домены прототипа,
# захардкоженные здесь как удобный дефолт. Пост-codemod (переезд в tooling/) набор
# инжектируется app-слоем (прототип передаёт свои паттерны), а модульный дефолт
# сузится до generic ``processes.**``/``system.**``. Сейчас поведение НЕ меняем.
GUI_DEFAULT_PATTERNS: tuple[str, ...] = (
    "processes.**",
    "system.**",
    "devices.**",
    "calibration.**",
)


class WatchController:
    """Владелец состояния watch-профиля; команды идут через back-ref на driver."""

    def __init__(self, driver: Any) -> None:
        self._d = driver
        # Состояние профиля. Лок остаётся: manifest/resume/default_tail_level
        # читаются из чужих потоков (MCP-сессия, reader), а start/stop пишут.
        self._watch_lock = threading.Lock()
        self._watch_active = False
        self._watch_patterns: tuple[str, ...] = ()  # реально включённые watch-паттерны (для unwatch)
        self._watch_tail_level = "WARNING"  # объявленный порог логов (для watch-манифеста, F2)

    def start(
        self,
        *,
        patterns: tuple[str, ...] = GUI_DEFAULT_PATTERNS,
        tail_level: str = "WARNING",
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Включить ВЕСЬ приёмный профиль GUI одной командой (state + observability-хвост).

        Одна команда даёт агенту ровно то, что получает GUI:

          - ``state.subscribe`` на каждый wildcard из ``patterns`` (по умолчанию
            :data:`GUI_DEFAULT_PATTERNS` — зеркало ``frontend/process.py``);
          - ``observability.tail.subscribe_all`` — ОДИН вызов брокеру PM, который
            разворачивает намерение на все живые процессы и переподписывает
            свежие инкарнации сам (Task 5.11.h).

        Всё приходит в ЕДИНУЮ очередь ``events``; записи наблюдаемости раскладывает по
        плоскостям ``observability_records``. Кадры/SHM через сокет НЕ гоняются (Dict at
        Boundary) — вне контракта watch.

        Сводка best-effort: недоступный источник — честная запись об ошибке, остальные
        работают. Повторный вызов при активном watch сначала делает :meth:`stop_profile`
        (чистый рестарт профиля).

        **Переподписки здесь больше нет.** Свежая инкарнация получает хвост от
        брокера — по шву ``_mark_instance_started``, через который проходят все пять
        путей старта. Прежний триггер (supervisor-событие ``recovered``) не покрывал
        ручной рестарт и switch: это и был резидуал F4.

        Args:
            patterns: набор state-wildcard'ов (по умолчанию GUI-набор).
            tail_level: декларируемый порог логов. **Замечание:** observability.tail
                форвардит ВСЕ плоскости и severity без фильтра на проводе, поэтому
                уровень применяется на стороне клиента —
                ``observability_records(kind="error")`` и т.п. Возвращается в сводке
                как объявленное намерение (сервер его не срезает).
            timeout: таймаут каждой под-команды.

        Returns:
            Сводка: ``{"state": {pattern: res}, "observability": {...ответ брокера},
            "processes": [...], "tail_level": ..., "success": bool}``.
        """
        if self._watch_active:
            self.stop_profile(timeout=timeout)

        summary: Dict[str, Any] = {
            "state": {},
            "observability": {},
            "processes": [],
            "tail_level": tail_level,
        }

        with self._watch_lock:
            self._watch_active = True
            self._watch_patterns = tuple(patterns)  # запомнить фактический набор для unwatch
            self._watch_tail_level = tail_level

        for pattern in patterns:
            summary["state"][pattern] = self._d.state_subscribe(pattern, timeout=timeout)

        # ОДИН вызов вместо цикла по топологии. Себя драйвер не исключает: инвариант
        # «не подписывай себя на себя» живёт у процесса (Task 5.11.c), а не у каждого
        # потребителя — иначе третий забудет.
        summary["observability"] = self._d.observability_tail_all(timeout=timeout)

        # Имена процессов — для читаемости сводки (кого накрыло намерение). Это
        # СПРАВКА, а не источник подписки: брокер накроет и тех, кто появится после.
        try:
            summary["processes"] = list(self._d._discover_processes(timeout=timeout))
        except Exception as exc:  # noqa: BLE001 — справочное поле не роняет профиль
            summary["processes_error"] = str(exc)

        state_ok = any((r or {}).get("success") is not False for r in summary["state"].values())
        obs_ok = (summary["observability"] or {}).get("success") is not False
        summary["success"] = bool(state_ok and obs_ok)
        return summary

    def stop_profile(self, *, timeout: Optional[float] = None) -> Dict[str, Any]:
        """Выключить GUI-профиль: снять намерение «хочу всё» + state-подписки.

        Одно ``unsubscribe_all`` вместо цикла untail по запомненным именам — и это
        не только короче: список имён к моменту unwatch мог разойтись с реальностью
        (switch пересоздал процессы), а брокер снимает по НАМЕРЕНИЮ, не по снимку.

        Durable-намерения вычищаются, чтобы будущий реконнект НЕ воскресил снятый
        профиль. Серверную state-подписку снимаем через ``state_unsubscribe``
        (durable-намерение; серверная подписка освобождается закрытием соединения).

        F2 (б, реконнект без восстановления контура): даже при ``was_active=False``
        всё равно чистим watch-намерения, чтобы «полу-durable» watch не воскрес молча.
        """
        with self._watch_lock:
            was_active = self._watch_active
            self._watch_active = False
            # Снять ровно те паттерны, что включал start (не хардкод — кастомный набор
            # иначе утёк бы в реестре). Fallback на GUI-набор — только если контур был
            # потерян при реконнекте (was_active=False, паттерны не восстановлены).
            patterns = (
                self._watch_patterns if self._watch_patterns else (GUI_DEFAULT_PATTERNS if not was_active else ())
            )
            self._watch_patterns = ()

        summary: Dict[str, Any] = {"observability": {}, "was_active": was_active}
        summary["observability"] = self._d.observability_untail_all(timeout=timeout)

        # Снять durable state.subscribe watch-паттернов через явную обёртку.
        for pattern in patterns:
            self._d.state_unsubscribe(pattern, timeout=timeout)

        # F2 (б): подчистить ЛЮБЫЕ висящие obs-tail-намерения (watch-owned), если контур
        # был потерян — иначе полу-durable watch воскреснет при реконнекте. Снимаем ОБЕ
        # формы: брокерную и per-process (профиль мог быть поднят версией до 5.11.h).
        if not was_active:
            self._d._subscriptions.remove_by_command("observability.tail.subscribe_all")
            self._d._subscriptions.remove_by_command("observability.tail.subscribe")

        summary["success"] = True
        return summary

    def stop(self) -> None:
        """Погасить клиентское состояние watch на ``close()`` driver'а.

        До 5.11.h здесь гасился applier-поток. Потока нет — остаётся только снять
        флаг: сеть на закрывающемся сокете не трогаем (намерение у брокера снимет
        либо явный ``unwatch``, либо закрытие соединения на стороне PM).
        """
        with self._watch_lock:
            self._watch_active = False

    def default_tail_level(self) -> Optional[str]:
        """Объявленный tail_level активного watch (или None) — дефолт severity-фильтра (F5)."""
        with self._watch_lock:
            return self._watch_tail_level if self._watch_active else None

    def manifest(self) -> Dict[str, Any]:
        """Снимок активного watch-профиля для переживания реконнекта (F2).

        MCP-сервер сохраняет манифест ДО сброса driver'а и после реконнекта передаёт
        его новому driver'у (:meth:`resume`).

        Списка процессов в манифесте больше нет (5.11.h): подписка держится ОДНИМ
        намерением у брокера, а имена к моменту реконнекта могли устареть — хранить
        их значило бы восстанавливать снимок вместо намерения.
        """
        with self._watch_lock:
            if not self._watch_active:
                return {"active": False}
            return {
                "active": True,
                "patterns": list(self._watch_patterns),
                "tail_level": self._watch_tail_level,
            }

    def resume(self, manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Восстановить watch-профиль из манифеста ПОСЛЕ реконнекта (F2, парный к :meth:`manifest`).

        Поднимает клиентское состояние БЕЗ повторных подписок: серверные
        ``state.subscribe``/``observability.tail.subscribe_all`` уже восстановлены
        replay'ем durable-намерений (``replay_subscriptions``) на новом соединении.

        Нет активного watch в манифесте → no-op. Идемпотентно.
        """
        if not manifest or not manifest.get("active"):
            return {"resumed": False}

        patterns = tuple(manifest.get("patterns") or ())
        with self._watch_lock:
            self._watch_active = True
            self._watch_patterns = patterns
            self._watch_tail_level = str(manifest.get("tail_level") or "WARNING")
        return {"resumed": True, "patterns": list(patterns)}
