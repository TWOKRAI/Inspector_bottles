# -*- coding: utf-8 -*-
"""mcp_driver_session.py — жизненный цикл driver'а под MCP-сервером (общий слой).

Тонкая, но критичная логика, общая для рукописного и SDK-сервера:
  * ленивое подключение driver'а к сокету живого бэкенда + readiness-проба;
  * durable-подписки переживают реконнект (export → replay на новом driver'е);
  * watch-профиль переживает реконнект (манифест → resume_watch поднимает контур);
  * одноразовый отчёт о реконнекте вливается в следующий tool-ответ.

Вынесено из ``mcp_server.py``, чтобы обе реализации сервера (транспорт/маршрутизация)
делили ОДНУ реализацию lifecycle, а не расходящиеся копии (Task 3.1).
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, Optional

from backend_ctl.driver import BackendDriver
from backend_ctl.endpoint_config import resolve_endpoint


class BackendUnavailable(RuntimeError):
    """Бэкенд недоступен (сокет не поднят/оборван) — понятный текст для агента."""


def _extract_backend_ctl_isolation(stats: Any) -> Optional[bool]:
    """Найти ``session_isolation`` канала ``backend_ctl`` в дереве ``introspect.router_stats``.

    Форма ответа может отличаться между версиями (channels — dict-по-имени или список),
    поэтому рекурсивный обход по dict/list: ищем узел с ``name == "backend_ctl"`` и полем
    ``session_isolation`` (его кладёт ``SocketChannel.get_info``). ``None`` → не найдено.
    """
    if isinstance(stats, dict):
        if stats.get("name") == "backend_ctl" and "session_isolation" in stats:
            return bool(stats["session_isolation"])
        for value in stats.values():
            found = _extract_backend_ctl_isolation(value)
            if found is not None:
                return found
    elif isinstance(stats, (list, tuple)):
        for value in stats:
            found = _extract_backend_ctl_isolation(value)
            if found is not None:
                return found
    return None


class DriverSession:
    """Владелец жизненного цикла одного :class:`BackendDriver` под MCP-сервером.

    Держит ленивое соединение; при сбросе сохраняет durable-намерения подписки и
    снимок watch-профиля, чтобы следующий :meth:`ensure` (реконнект) их восстановил.
    Не знает про транспорт/JSON-RPC — сервер (любой) дергает :meth:`ensure`/:meth:`reset`.
    """

    def __init__(
        self,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        request_timeout: float = 5.0,
        driver_factory: Any = None,
        log: Any = None,
        require_isolation: bool = False,
    ) -> None:
        self._host, self._port = resolve_endpoint(host, port)
        self._request_timeout = request_timeout
        # D.2 §5.4: HTTP-мультиклиент требует backend session_isolation=ON (иначе broadcast
        # протекает между сессиями). Ставится HTTP-раннером; stdio (один клиент) — False.
        self._require_isolation = require_isolation
        self._isolation_ok = False  # проба выполняется один раз при первом ensure()
        # Фабрика для тестов: () → объект с интерфейсом BackendDriver (fake).
        self._driver_factory = driver_factory or self._default_driver_factory
        self._driver: Optional[BackendDriver] = None
        # Durable-подписки переживают реконнект driver'а (Task 0.3): при сбросе
        # driver'а его намерения сохраняются здесь и replay'ятся на новый driver.
        self._sub_intents: list = []
        # F2: манифест активного watch-профиля переживает реконнект — после replay'я
        # намерений новый driver ПОДНИМАЕТ watch-контур (слушатель+applier).
        self._watch_manifest: Optional[Dict[str, Any]] = None
        # Одноразовый отчёт (реконнект / прогрев) — вливается в следующий tool-ответ.
        self._reconnect_report: Optional[Dict[str, Any]] = None
        # A.4: подтверждена ли готовность PM readiness-пробой. False → бэкенд ещё
        # прогревается (первый вызов может таймаутить) — не молчим об этом.
        self._ready: bool = True
        self._log = log or (lambda m: print(m, file=sys.stderr, flush=True))

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    # ---- Фабрика + readiness ----

    def _default_driver_factory(self) -> BackendDriver:
        drv = BackendDriver(self._host, self._port, default_timeout=self._request_timeout)
        drv.connect()
        # Readiness-проба вместо фиксированного sleep (Task 0.3): ждём, пока
        # SocketChannel зарегистрирует клиента и PM начнёт отвечать.
        self._await_ready(drv)
        return drv

    def _await_ready(self, drv: BackendDriver, *, attempts: int = 3, probe_timeout: float = 2.0) -> bool:
        """Пинг-проба готовности PM (3 ретрая). best-effort: неответ не бросает.

        A.4: если готовность НЕ подтверждена за дедлайн — больше не молчим. Ставим
        флаг ``_ready=False``, логируем warning и кладём одноразовый маркер
        ``backend_warming`` в следующий tool-ответ, чтобы агент видел причину
        непонятного таймаута первого вызова (бэкенд ещё прогревается), а не гадал.
        """
        for _ in range(attempts):
            try:
                res = drv.introspect_status("ProcessManager", timeout=probe_timeout)
            except Exception:  # noqa: BLE001 — проба не должна ронять старт
                res = None
            if isinstance(res, dict) and res.get("success") is True:
                self._ready = True
                return True
            time.sleep(0.1)
        self._ready = False
        self._log(
            f"[mcp] readiness: PM на {self._host}:{self._port} не подтвердил готовность за "
            f"{attempts}×{probe_timeout}s — бэкенд прогревается, первый вызов может таймаутить"
        )
        self._note_report(backend_warming=True)
        return False

    def _note_report(self, **fields: Any) -> None:
        """Домержить поля в одноразовый tool-отчёт (реконнект/прогрев не затирают друг друга)."""
        report = self._reconnect_report or {}
        report.update(fields)
        self._reconnect_report = report

    # ---- Lifecycle ----

    def ensure(self) -> BackendDriver:
        """Лениво подключить driver; при недоступном бэкенде — :class:`BackendUnavailable`.

        После реконнекта (driver был сброшен, но остались durable-подписки) новый
        driver получает намерения и replay'ит их — поток событий не теряется молча.
        """
        if self._driver is None:
            try:
                self._driver = self._driver_factory()
            except OSError as exc:
                raise BackendUnavailable(
                    f"бэкенд недоступен на {self._host}:{self._port} ({exc}). "
                    "Подними систему с BACKEND_CTL=1 (например `python multiprocess_prototype/run.py` "
                    "или BackendHarness) и повтори вызов."
                ) from exc
            except Exception as exc:  # noqa: BLE001 — любое исключение фабрики → понятный контракт
                # Контракт «driver не бросает» — на уровне сессии: не-OSError (сборка
                # driver'а, кривой fake, protocol) тоже становится BackendUnavailable,
                # а не сырым исключением сквозь MCP-протокол.
                raise BackendUnavailable(
                    f"не удалось поднять driver к {self._host}:{self._port} "
                    f"({type(exc).__name__}: {exc}). Проверь, что бэкенд запущен с BACKEND_CTL=1."
                ) from exc
            # Реконнект: восстановить durable-подписки на новом driver'е (Task 0.3).
            if self._sub_intents:
                self._driver.import_subscriptions(self._sub_intents)
                resubscribed = self._driver.replay_subscriptions()
                self._note_report(reconnected=True, resubscribed=resubscribed)
                self._log(f"[mcp] реконнект: replay {len(resubscribed)} подписк(и)")
            # F2: если watch был активен — поднять watch-КОНТУР на новом driver'е (слушатель
            # + applier). Серверные подписки уже восстановлены replay'ем выше; resume_watch
            # НЕ переподписывает, только оживляет авто-resub и делает unwatch управляемым.
            if self._watch_manifest and self._watch_manifest.get("active") and hasattr(self._driver, "resume_watch"):
                wr = self._driver.resume_watch(self._watch_manifest)
                self._note_report(reconnected=True, watch_resumed=bool(isinstance(wr, dict) and wr.get("resumed")))
                self._log(f"[mcp] реконнект: watch-контур восстановлен ({wr})")
        # D.2 §5.4: fail-fast, если HTTP-режим требует изоляции, а бэкенд поднят broadcast'ом.
        # Одна проба на сессию (existing router-ручка); OFF/непрочитано → громкий отказ,
        # НЕ тихая работа с протечкой между сессиями.
        if self._require_isolation and not self._isolation_ok:
            self._probe_isolation(self._driver)
            self._isolation_ok = True
        return self._driver

    def _probe_isolation(self, drv: BackendDriver) -> None:
        """Проверить, что бэкенд поднят с session_isolation=ON (D.2 §5.4). Иначе broadcast
        протекает между HTTP-сессиями — мультиклиент опаснее его отсутствия. Читает флаг
        существующей ручкой ``introspect.router_stats`` (ноль правок бэкенда). OFF или
        непрочитанный флаг → :class:`BackendUnavailable` с actionable-текстом."""
        try:
            stats = drv.introspect_router_stats("ProcessManager", timeout=self._request_timeout)
        except Exception as exc:  # noqa: BLE001 — контракт «понятная ошибка», не сырое исключение
            raise BackendUnavailable(
                f"не удалось проверить session-isolation бэкенда на {self._host}:{self._port} ({exc})."
            ) from exc
        iso = _extract_backend_ctl_isolation(stats)
        if iso is True:
            return
        if iso is False:
            raise BackendUnavailable(
                "HTTP-мультиклиент требует backend session_isolation=ON, а бэкенд поднят с broadcast "
                "(протечка reply/событий между сессиями). Перезапусти бэкенд с "
                "BACKEND_CTL_SESSION_ISOLATION=1 (или config backend_ctl.session_isolation=true)."
            )
        raise BackendUnavailable(
            "не удалось прочитать session_isolation канала backend_ctl из introspect.router_stats — "
            "обнови бэкенд до версии с session-isolation (D.1) или используй stdio-режим."
        )

    def reset(self) -> None:
        """Сбросить соединение (следующий :meth:`ensure` переподключится).

        Durable-намерения подписки и снимок watch-профиля сохраняются ДО закрытия
        driver'а, чтобы новый driver мог их restore'нуть (иначе подписки/watch
        терялись бы молча — Task 0.3 / F2).
        """
        if self._driver is not None:
            try:
                # Синхронизируем БЕЗУСЛОВНО (в т.ч. с пустым списком): текущий driver —
                # источник правды. Если агент отписался — registry пуст, и replay при
                # следующем реконнекте НЕ должен воскрешать снятые подписки (ревью MAJOR #1).
                self._sub_intents = self._driver.export_subscriptions()
            except Exception:  # noqa: BLE001 — экспорт не должен ронять сброс
                pass
            # F2: снять снимок watch-профиля ДО закрытия (источник правды — текущий driver).
            if hasattr(self._driver, "watch_manifest"):
                try:
                    self._watch_manifest = self._driver.watch_manifest()
                except Exception:  # noqa: BLE001 — снимок не должен ронять сброс
                    self._watch_manifest = None
            try:
                self._driver.close()
            except Exception:  # noqa: BLE001 — сброс не должен падать
                pass
            self._driver = None

    def pop_reconnect_report(self) -> Optional[Dict[str, Any]]:
        """Забрать одноразовый отчёт о реконнекте (и очистить) — для вливания в tool-ответ."""
        report = self._reconnect_report
        self._reconnect_report = None
        return report

    def close_graceful(self, *, timeout: float = 1.0) -> None:
        """Закрыть сессию, СНЯВ durable-подписки на бэкенде, пока сокет ещё жив (D.2 §5.2).

        Долг D.1 §12: :meth:`close`/:meth:`reset` лишь закрывают сокет — durable-регистрации
        ``backend_ctl.<sid>`` осиротели бы на бэкенде. Здесь ДО закрытия: ``unwatch`` (сетевой
        teardown watch-контура, если активен) → ``unsubscribe_all`` (реестр → снимающие
        команды). Всё SYNC с коротким таймаутом: зовётся из выхода lifespan, в т.ч. при
        idle-reap (отменённый cancel-scope) — ``await`` недопустим, виснуть нельзя. Best-effort:
        бэкенд мёртв → просто закрываем (:meth:`reset`).
        """
        drv = self._driver
        if drv is not None:
            if hasattr(drv, "unwatch"):
                try:
                    drv.unwatch()
                except Exception:  # noqa: BLE001 — best-effort teardown перед закрытием
                    pass
            if hasattr(drv, "unsubscribe_all"):
                try:
                    drv.unsubscribe_all(timeout=timeout)
                except Exception:  # noqa: BLE001 — best-effort teardown перед закрытием
                    pass
        self.reset()

    def close(self) -> None:
        self.reset()


__all__ = ["BackendUnavailable", "DriverSession"]
