# -*- coding: utf-8 -*-
"""mcp_driver_session.py — жизненный цикл driver'а под MCP-сервером (общий слой).

Тонкая, но критичная логика, общая для рукописного и SDK-сервера:
  * ленивое подключение driver'а к сокету живого бэкенда + readiness-проба;
  * durable-подписки переживают реконнект (export → replay на новом driver'е);
  * watch-профиль переживает реконнект (манифест → resume_watch поднимает контур);
  * одноразовый отчёт о реконнекте вливается в следующий tool-ответ.

Изначально вынесено из рукописного ``mcp_server.py`` (удалён в F.1, BCTL-ADR-001),
чтобы обе реализации сервера (транспорт/маршрутизация) делили ОДНУ реализацию
lifecycle, а не расходящиеся копии (Task 3.1); теперь единственный сервер —
:mod:`backend_ctl.mcp_server_sdk`, но модуль сохранён отдельным слоем на случай
будущей альтернативной реализации транспорта.
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Any, Dict, Optional

from backend_ctl.audit import AuditLog
from backend_ctl.command_validate import target_unknown, validate_command_args
from backend_ctl.driver import BackendDriver
from backend_ctl.endpoint_config import resolve_endpoint
from backend_ctl.mcp_errors import BackendUnavailable
from backend_ctl.recorder import (
    MODE_LIVE,
    MODE_REPLAY,
    REASON_DISCONNECT,
    Recorder,
    ReplayPlayer,
    load_recording,
)
from backend_ctl.recorder import (
    dump_recording as _dump_recording_file,  # алиас: не путать с методом DriverSession.dump_recording
)


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
        audit_log: Optional[AuditLog] = None,
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
        # Flight recorder (D.4): режим live|replay + владение активной записью/реплеем.
        # Запись привязана к текущему live-driver'у; reset() финализирует её footer'ом
        # disconnect ДО закрытия (файл не остаётся без footer'а). Реплей — session-локальный
        # detached-driver (ensure() в replay НЕ коннектится).
        self._mode: str = MODE_LIVE
        self._recorder: Optional[Recorder] = None
        self._replay: Optional[ReplayPlayer] = None
        # ОДИН лок на весь жизненный цикл сессии: driver (ensure/reset), recorder,
        # реплей, кэш capabilities, ленивый аудит-журнал. Каждый tools/call уходит в свой
        # поток (SDK-сервер: anyio.to_thread.run_sync + tg.start_soon, без per-session
        # очереди), поэтому все пары «проверил — присвоил» здесь обязаны быть атомарными:
        # два параллельных record_start иначе оба проходят, и запись, потерявшая ссылку,
        # навсегда остаётся осиротевшим подписчиком на hot-path EventHub; два параллельных
        # ensure() создают два driver'а, и один утекает вместе с сокетом и reader-потоком.
        #
        # Почему ОДИН лок, а не отдельные (Task 2.1): recorder и driver переплетены в обе
        # стороны — ensure() → reset() финализирует запись, а start_recording() заходит в
        # ensure(). Два лока дали бы разный порядок захвата на этих путях (AB-BA) и живой
        # дедлок под нагрузкой. RLock: перечисленные пути повторно заходят под свой же лок.
        self._lifecycle_lock = threading.RLock()
        # E.1: аудит-журнал мутаций (write/escalated) сессии. Ленивая инициализация
        # файла — при первой записи (read-only-сессия не создаёт файл). Тест может
        # подставить свой AuditLog.
        self._audit: Optional[AuditLog] = audit_log
        # E.2: кэш свода capabilities (для клиентской валидации send_command). Строится
        # лениво при первой валидации; refresh — при неизвестном адресате (мог hot-added).
        self._caps: Any = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def mode(self) -> str:
        """Режим сессии: ``live`` (бэкенд) или ``replay`` (загруженная запись, D.4)."""
        return self._mode

    @property
    def replay_player(self) -> Optional[ReplayPlayer]:
        """Активный реплеер (в replay-режиме) либо None."""
        return self._replay

    # ---- Flight recorder (D.4) ----

    def start_recording(
        self,
        path: str,
        *,
        max_events: Optional[int] = None,
        max_bytes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Начать запись потока событий текущего live-driver'а в ``path``.

        В replay-режиме запись не имеет смысла (нет живого потока) — обучающий отказ.
        Уже идёт запись — отказ (одна запись = один файл).
        """
        with self._lifecycle_lock:
            if self._mode == MODE_REPLAY:
                return {
                    "success": False,
                    "error": "нельзя писать в replay-режиме: сначала record_unload() для возврата к live",
                }
            if self._recorder is not None and self._recorder.active:
                return {"success": False, "error": f"запись уже идёт в {self._recorder.path!r} — сначала record_stop()"}
            drv = self.ensure()  # live-driver (может бросить BackendUnavailable — ловит сервер)
            kwargs: Dict[str, Any] = {}
            if max_events is not None:
                kwargs["max_events"] = int(max_events)
            if max_bytes is not None:
                kwargs["max_bytes"] = int(max_bytes)
            recorder = Recorder(drv, path, **kwargs)
            out = recorder.start()
            # Ссылку публикуем только на успешном старте: неудачно стартовавший Recorder
            # не должен занять слот сессии и заблокировать следующий record_start.
            if out.get("success"):
                self._recorder = recorder
            return out

    def stop_recording(self) -> Dict[str, Any]:
        """Остановить активную запись (footer reason=stopped). Нет записи → обучающий отказ."""
        with self._lifecycle_lock:
            if self._recorder is None:
                return {"success": False, "error": "нет активной записи (record_start сначала)"}
            status = self._recorder.stop()
            self._recorder = None
            return status

    def dump_recording(self, path: str) -> Dict[str, Any]:
        """One-shot дамп текущего arrival-кольца live-driver'а (§5.3, чёрный ящик)."""
        with self._lifecycle_lock:
            if self._mode == MODE_REPLAY:
                return {
                    "success": False,
                    "error": "record_dump доступен только в live-режиме (record_unload для возврата)",
                }
            drv = self.ensure()
            return _dump_recording_file(drv, path)

    def record_status(self) -> Dict[str, Any]:
        """Статус: активная запись (файл/счётчики) ЛИБО загруженный реплей (имя/позиция)."""
        with self._lifecycle_lock:
            if self._replay is not None:
                return self._replay.status()
            if self._recorder is not None:
                return self._recorder.status()
            return {"success": True, "mode": self._mode, "recording": False, "replay": False}

    def load_replay(
        self,
        path: str,
        *,
        position: str = "end",
        ring_maxlen: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Загрузить запись в offline-реплей (detached driver); перевести сессию в replay.

        Активная запись сначала должна быть остановлена (одна активность на сессию).
        Реплей ничего не пишет и не коннектится — session-локальный режим.
        """
        with self._lifecycle_lock:
            if self._recorder is not None and self._recorder.active:
                return {"success": False, "error": "идёт запись — сначала record_stop() перед загрузкой реплея"}
            recording = load_recording(path)  # RecordingError ловит сервер (обучающий текст)
            self._replay = ReplayPlayer(recording, position=position, ring_maxlen=ring_maxlen)
            self._mode = MODE_REPLAY
            # Квиесцировать live-driver (Task 2.1, находка C-3): в replay-режиме ensure()
            # его больше не отдаёт, но сам он оставался подключённым — сокет, reader-поток
            # и серверные подписки продолжали жить и копить события в никуда. Намерения
            # сохраняются, поэтому unload_replay() → ensure() честно переподключится.
            self._reset_driver_locked()
            out = self._replay.status()
            out["truncated"] = recording.truncated
            out["position_mode"] = position
            return out

    def unload_replay(self) -> Dict[str, Any]:
        """Выгрузить реплей, вернуть сессию в live (следующий ensure() переподключится)."""
        with self._lifecycle_lock:
            if self._replay is None:
                return {"success": False, "error": "нет загруженного реплея (record_load сначала)"}
            self._replay = None
            self._mode = MODE_LIVE
            return {"success": True, "mode": MODE_LIVE, "unloaded": True}

    # ---- Аудит мутаций (E.1) ----

    def _audit_log(self) -> AuditLog:
        """Ленивая инициализация журнала (файл создаётся при первой записи).

        Под локом (Task 2.1): два параллельных write-инструмента иначе создавали по
        своему AuditLog, и записи одного из них уходили в потерянный объект — журнал
        доверия обязан быть один на сессию.
        """
        if self._audit is None:
            with self._lifecycle_lock:
                if self._audit is None:
                    self._audit = AuditLog()
        return self._audit

    def record_audit(
        self,
        tool: str,
        safety: str,
        args: Any,
        *,
        result: Any = None,
        error: Optional[BaseException] = None,
    ) -> None:
        """Записать write/escalated-вызов в журнал. Best-effort (сбой не бросается)."""
        try:
            self._audit_log().record(tool, safety, args, result=result, error=error)
        except Exception:  # noqa: BLE001 — аудит наблюдает, не мешает инструменту
            pass

    def read_audit(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """Хвост журнала мутаций ЭТОЙ сессии (для session_log()). Пустой журнал — [] и path."""
        if self._audit is None:
            return {"success": True, "entries": [], "count": 0, "path": None}
        entries = self._audit.records(limit)
        return {
            "success": True,
            "entries": entries,
            "count": len(entries),
            "path": self._audit.path,
        }

    # ---- Валидация send_command по схеме (E.2) ----

    def capabilities_cache(self, *, refresh: bool = False) -> Any:
        """Свод capabilities (кэш сессии). ``refresh`` — перечитать с бэкенда.

        Best-effort: сбой сбора возвращает ``None`` (валидатор тогда пропускает — не
        мешает работе из-за собственной неспособности прочитать схему). В replay-режиме
        живого свода нет — тоже ``None``.
        """
        if self._mode == MODE_REPLAY:
            return None
        if self._caps is not None and not refresh:
            return self._caps
        # Пара «проверил — собрал — присвоил» под локом (Task 2.1): иначе два потока
        # собирают свод дважды, дёргая бэкенд лишний раз.
        with self._lifecycle_lock:
            if self._caps is not None and not refresh:
                return self._caps  # сосед успел собрать, пока мы ждали лок
            try:
                drv = self.ensure()
                self._caps = drv.capabilities()
            except Exception:  # noqa: BLE001 — валидация опциональна, не роняем инструмент
                # НЕ затираем удачный кэш соседа своей неудачей: обнуляем только если
                # кэша всё ещё нет. Иначе один сбойный сбор ослеплял бы валидацию
                # send_command для всей сессии.
                if self._caps is None:
                    self._caps = None
            return self._caps

    def validate_send_command(self, arguments: Dict[str, Any]) -> Optional[str]:
        """Сверить args send_command со схемой свода ДО отправки. ``None`` — ок; строка — ошибка.

        Неизвестный адресат → один refresh кэша (процесс мог быть hot-added), затем
        повторная проверка. Пустой target/command — не наша забота (обязательность полей
        инструмента гейтит клиент MCP); валидируем лишь заявленные значения.
        """
        target = arguments.get("target")
        command = arguments.get("command")
        if not target or not command:
            return None
        caps = self.capabilities_cache()
        if caps is None:
            return None
        if target_unknown(caps, target):
            caps = self.capabilities_cache(refresh=True)
            if caps is None:
                return None
        return validate_command_args(caps, target, command, arguments.get("args"))

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

        В replay-режиме (D.4) возвращает detached-driver реплеера БЕЗ connect и без
        isolation-пробы — offline read-model уже наполнен записью.
        """
        if self._mode == MODE_REPLAY and self._replay is not None:
            return self._replay.driver

        # Быстрый путь БЕЗ лока (Task 2.1): живой driver с уже пройденной isolation-пробой.
        # Так редкий коннект одного потока не сериализует все параллельные tools/call —
        # лок берётся только теми, кто реально меняет жизненный цикл.
        drv = self._driver
        isolation_settled = self._isolation_ok or not self._require_isolation
        if drv is not None and isolation_settled and not getattr(drv, "connection_lost", False):
            return drv

        with self._lifecycle_lock:
            # Перепроверка под локом: пока мы ждали его, сосед мог уже всё сделать —
            # иначе двое создадут по driver'у, и один утечёт с сокетом и reader-потоком.
            self._ensure_locked()
            return self._driver

    def _ensure_locked(self) -> None:
        """Тело :meth:`ensure` под ``_lifecycle_lock`` — создание/реконнект driver'а."""
        # Task 1.1: driver с мёртвым транспортом бесполезен — сбросить и пересоздать здесь,
        # не дожидаясь, пока следующий вызов упадёт. reset() успевает снять durable-намерения
        # и watch-манифест с умирающего driver'а, поэтому реконнект ниже их восстановит.
        if self._driver is not None and getattr(self._driver, "connection_lost", False):
            self._log("[mcp] соединение с бэкендом мертво — пересоздаю driver")
            self.reset()
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
        # ревью #2: None = флаг не найден в ответе. Причин две — не смешиваем в диагностике.
        raise BackendUnavailable(
            "не удалось прочитать session_isolation канала backend_ctl из introspect.router_stats "
            "(бэкенд без session-isolation D.1 ЛИБО router_stats недоступен/вернул ошибку). "
            "Обнови бэкенд до версии с session-isolation или используй stdio-режим."
        )

    def reset(self) -> None:
        """Сбросить соединение (следующий :meth:`ensure` переподключится).

        Durable-намерения подписки и снимок watch-профиля сохраняются ДО закрытия
        driver'а, чтобы новый driver мог их restore'нуть (иначе подписки/watch
        терялись бы молча — Task 0.3 / F2).

        D.4: активная запись финализируется footer'ом ``disconnect`` ДО закрытия
        driver'а — файл не остаётся без footer'а на обрыве/реконнекте сессии.
        """
        # Весь сброс — под локом жизненного цикла (Task 2.1): иначе параллельный ensure()
        # успевал увидеть уже закрытый, но ещё не обнулённый driver, а параллельный
        # record_start — привязать запись к driver'у, который мы в этот момент закрываем.
        with self._lifecycle_lock:
            # Финализировать активную запись ДО закрытия driver'а (footer=disconnect).
            if self._recorder is not None:
                try:
                    self._recorder.stop(REASON_DISCONNECT)
                except Exception:  # noqa: BLE001 — финализация не должна ронять сброс
                    pass
                self._recorder = None
            self._reset_driver_locked()

    def _reset_driver_locked(self) -> None:
        """Снять намерения/манифест и закрыть driver. Только под ``_lifecycle_lock``."""
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


__all__ = ["BackendUnavailable", "DriverSession", "MODE_LIVE", "MODE_REPLAY"]
