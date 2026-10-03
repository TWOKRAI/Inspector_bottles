# -*- coding: utf-8 -*-
"""Сессия прибора через MvCodeReader SDK: открыть, крутить захват в потоке, отдать кадр.

Владение handle. Открытие одно на ``start()``, поток захвата — один на открытие, и
отпускает прибор (``stop_grabbing`` + ``close``) только он сам, в ``finally`` после
выхода из цикла: единственный вызывающий ``_release``, поэтому остановка и аварийный
выход не закроют прибор дважды, а ``close`` не пойдёт под идущим ``get_frame``
(на Windows закрытие не будит блокирующий вызов, а буфер кадра освобождается).
Отказ на ``start_grabbing`` закрывает handle в ``start()`` — поток там ещё не создан.
``stop()`` лишь поднимает событие и ждёт поток ``timeout + timeout_ms``: дедлайн
держится на собственном таймауте ``get_frame``.

Автопереподключения нет (решение 6 плана): после трёх ошибок ``get_frame`` подряд
прибор закрывается, состояние ``error``, дальше — ``stop()``/``start()`` снаружи.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from multiprocess_framework.modules.logger_module import get_std_logger
from Services.code_reader.core.result import ReadStatus
from Services.code_reader.core.sdk_frame import SdkFrame, frame_from_raw
from Services.code_reader.sdk.errors import E_ACCESS_DENIED, SdkError

_log = get_std_logger(__name__)

# Столько ошибок get_frame подряд (E_NODATA не в счёт) переводят сессию в "error".
MAX_CONSECUTIVE_ERRORS = 3

_LATE_STOP = "поток захвата не завершился за дедлайн stop(); прибор закроется, когда вернётся get_frame"
_BUSY_HINT = "прибор занят другим клиентом — закройте IDMVS (или другое приложение, открывшее прибор) и повторите"


def _exc_text(exc: BaseException) -> str:
    """Текст исключения вместе с ``__notes__``: ``str(exc)`` заметки не включает
    (так терялся код отказа DestroyHandle, приложенный к ошибке OpenDevice)."""
    return "; ".join([str(exc), *getattr(exc, "__notes__", ())])


@dataclass
class _Session:
    """Одно открытие прибора: handle и своё событие остановки (у задержавшегося потока — своё)."""

    handle: Any
    stop: threading.Event = field(default_factory=threading.Event)


class SdkCodeReader:
    """Держит прибор и отдаёт каждый кадр с кодами в ``on_frame`` из потока захвата.

    Состояния: ``stopped`` (исходное и после ``stop()``), ``running``, ``not_found``,
    ``busy``, ``error``. Колбэки зовутся из потока захвата (``on_error`` — ещё и из
    ``start()``) и захват не останавливают: исключение ``on_frame`` считается в ``errors``
    и уходит в ``on_error``; исключение самого ``on_error`` в ``errors`` НЕ считается —
    только пишется в лог.
    """

    def __init__(
        self,
        on_frame: Callable[[SdkFrame], None],
        on_error: Callable[[str], None] | None = None,
        *,
        device_ip: str | None = None,
        timeout_ms: int = 500,
        api: Any = None,
    ) -> None:
        if api is None:
            from Services.code_reader.sdk.api import MvCodeReaderApi

            api = MvCodeReaderApi()  # DLL грузится лениво, на первом вызове
        self._api = api
        self._on_frame = on_frame
        self._on_error = on_error
        self._device_ip = device_ip
        self._timeout_ms = int(timeout_ms)

        self._life = threading.Lock()  # сериализует start()/stop(); SDK-вызовы открытия идут под ним
        self._lock = threading.Lock()  # короткий: состояние и счётчики
        self._session: _Session | None = None
        self._thread: threading.Thread | None = None

        self._state = "stopped"
        self._device: dict[str, str] | None = None
        self._last_error: str | None = None
        self._counts = {"frames": 0, "ok": 0, "no_code": 0, "bad_code": 0, "errors": 0}

    # ------------------------------------------------------------------ публичное

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def start(self) -> bool:
        """Найти прибор, открыть, запустить захват и поток. ``True`` — захват идёт."""
        messages: list[str] = []
        try:
            with self._life:
                return self._start_locked(messages)
        finally:
            for msg in messages:
                self._emit(msg)

    def stop(self, timeout: float = 2.0) -> None:
        """Остановить захват и отпустить прибор. Идемпотентен; ждёт не дольше ``timeout + timeout_ms``."""
        # Под _life — только снять сессию и поднять событие; ждать поток — ВНЕ замка:
        # иначе stop() из on_frame (ему нужен _life) держал бы внешний stop() до дедлайна.
        # self._thread не обнуляется до выхода потока — по нему start() отказывает в
        # повторном открытии, пока старый handle не закрыт.
        with self._life:
            session, thread = self._session, self._thread
            self._session = None
            if session is not None:
                session.stop.set()
            with self._lock:
                self._state = "stopped"
        if thread is None or thread is threading.current_thread():
            # stop() из колбэка: ждать самого себя нельзя; поток отпустит прибор на выходе.
            return
        thread.join(timeout + self._timeout_ms / 1000)
        if thread.is_alive():
            # Прибор закроет сам поток, когда get_frame вернётся; закрыть сейчас — под вызовом.
            _log.warning("code_reader SDK: %s", self._note_error(_LATE_STOP))
        # self._thread НЕ обнуляем: для этого пришлось бы снова брать _life, а start() держит его
        # всё время enum/open — stop() вылезал бы за дедлайн (ревью 6.2 итерации 2, п.1: 12/20).
        # start() и так проверяет is_alive() — мёртвый поток повторному открытию не мешает.

    def stats(self) -> dict[str, Any]:
        # device_held: поток захвата ещё жив. Прибор отпускает только он (`_release` в finally),
        # поэтому после stop() с поздним get_frame это единственный честный ответ «прибор отпущен?».
        # self._thread читается без _life намеренно: stop()/start() держат его на весь enum/open.
        thread = self._thread
        with self._lock:
            return {
                **self._counts,
                "state": self._state,
                "last_error": self._last_error,
                "device": None if self._device is None else dict(self._device),
                "device_held": thread is not None and thread.is_alive(),
            }

    # ------------------------------------------------------------------ открытие

    def _start_locked(self, messages: list[str]) -> bool:
        if self._thread is not None and self._thread.is_alive():
            if self._state == "running":
                return True
            # Старый поток ещё отпускает прибор (после stop() или финального сбоя): второе
            # открытие наложилось бы на живой handle. Состояние и last_error не трогаем —
            # иначе start() из on_error на финальном сбое перетёр бы "error" и его причину.
            messages.append("предыдущий поток захвата ещё не завершился, повторите start() позже")
            return False

        try:
            entries = self._api.enum_devices()
        except Exception as exc:  # SdkError, SdkNotFoundError, отказ DLL
            messages.append(self._fail("error", f"поиск приборов не удался: {_exc_text(exc)}"))
            return False
        entry = next((e for e in entries if self._device_ip in (None, e.ip)), None)
        if entry is None:
            where = f"с IP {self._device_ip}" if self._device_ip else "ни одного"
            messages.append(self._fail("not_found", f"прибор {where} не найден"))
            return False

        try:
            handle = self._api.open(entry)  # при отказе OpenDevice handle уже уничтожен в sdk/
        except Exception as exc:
            messages.append(self._fail_open(entry, exc))
            return False

        try:
            self._api.start_grabbing(handle)
        except Exception as exc:
            try:
                self._api.close(handle)
            except Exception as close_exc:
                messages.append(self._note_error(f"close после отказа StartGrabbing: {_exc_text(close_exc)}"))
            messages.append(self._fail_open(entry, exc))
            return False

        session = _Session(handle)
        with self._lock:
            self._device = {"ip": entry.ip, "model": entry.model, "serial": entry.serial}
            self._state = "running"
        self._session = session
        self._thread = threading.Thread(target=self._run, args=(session,), name="code-reader-sdk", daemon=True)
        self._thread.start()
        return True

    def _fail_open(self, entry: Any, exc: Exception) -> str:
        if isinstance(exc, SdkError) and exc.code == E_ACCESS_DENIED:
            return self._fail("busy", f"{entry.ip}: {_BUSY_HINT} ({_exc_text(exc)})")
        return self._fail("error", f"{entry.ip}: открыть прибор не удалось: {_exc_text(exc)}")

    def _fail(self, state: str, message: str) -> str:
        with self._lock:
            self._state = state
            self._last_error = message
        return message

    # ------------------------------------------------------------------ поток

    def _run(self, session: _Session) -> None:
        failure: str | None = None
        try:
            try:
                failure = self._capture(session)
            except Exception as exc:  # дефект самого цикла — не умирать молча
                failure = f"поток захвата упал: {type(exc).__name__}: {_exc_text(exc)}"
                _log.exception("code_reader: поток захвата SDK упал")
            if failure is not None:
                # "error" — ДО _release: пока поток отпускает прибор, state уже не "running",
                # и start() с другой стороны получит отказ, а не True над умирающей сессией.
                with self._lock:
                    if not session.stop.is_set():
                        self._state = "error"
        finally:
            self._release(session)
        if failure is not None:
            # Причину — ПОСЛЕ _release: при обрыве кабеля падают и StopGrabbing/CloseDevice, и их
            # _note_error иначе перетёр бы в stats() первопричину (ревью 6.2 итерации 2, п.2: 20/20).
            with self._lock:
                self._last_error = failure
            self._emit(failure)

    def _capture(self, session: _Session) -> str | None:
        """Цикл захвата. Возвращает текст устойчивой ошибки или ``None`` при штатной остановке."""
        consecutive = 0
        while not session.stop.is_set():
            try:
                raw = self._api.get_frame(session.handle, self._timeout_ms)
            except Exception as exc:
                if session.stop.is_set():
                    return None  # stop() уже вернулся или идёт — результат вызова ничей
                consecutive += 1
                if consecutive >= MAX_CONSECUTIVE_ERRORS:
                    self._count_error()
                    return f"{consecutive} ошибки get_frame подряд, прибор закрыт; последняя: {_exc_text(exc)}"
                self._emit(self._note_error(f"get_frame: {_exc_text(exc)}"))
                continue
            if session.stop.is_set():
                # get_frame вернулся после stop(): кадр не разбираем, on_frame не зовём,
                # счётчики не трогаем — потребитель уже считает сессию остановленной.
                return None
            consecutive = 0  # E_NODATA (None) — тоже успешный вызов
            if raw is None:
                continue
            try:
                frame = frame_from_raw(raw)
            except Exception as exc:
                self._emit(self._note_error(f"разбор кадра: {type(exc).__name__}: {_exc_text(exc)}"))
                continue
            self._count_frame(frame)
            try:
                self._on_frame(frame)
            except Exception as exc:
                self._emit(self._note_error(f"on_frame: {type(exc).__name__}: {_exc_text(exc)}"))
        return None

    def _release(self, session: _Session) -> None:
        """``stop_grabbing`` + ``close``. Зовётся только из ``finally`` потока захвата — раз на открытие."""
        for name in ("stop_grabbing", "close"):
            try:
                getattr(self._api, name)(session.handle)
            except Exception as exc:
                self._emit(self._note_error(f"{name}: {_exc_text(exc)}"))

    # ------------------------------------------------------------------ учёт

    def _count_frame(self, frame: SdkFrame) -> None:
        key = {ReadStatus.OK: "ok", ReadStatus.BAD_CODE: "bad_code"}.get(frame.status, "no_code")
        with self._lock:
            self._counts["frames"] += 1
            self._counts[key] += 1

    def _count_error(self) -> None:
        with self._lock:
            self._counts["errors"] += 1

    def _note_error(self, message: str) -> str:
        with self._lock:
            self._counts["errors"] += 1
            self._last_error = message
        return message

    def _emit(self, message: str) -> None:
        _log.warning("code_reader SDK: %s", message)
        if self._on_error is None:
            return
        try:
            self._on_error(message)
        except Exception:
            _log.exception("code_reader: исключение в on_error")
