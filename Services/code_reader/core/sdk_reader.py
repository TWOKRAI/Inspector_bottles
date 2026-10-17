# -*- coding: utf-8 -*-
"""Сессия прибора через MvCodeReader SDK: открыть, крутить захват в потоке, отдать кадр.

Владение handle. Открытие одно на ``start()``, поток захвата — один на открытие, и
отпускает прибор (``stop_grabbing`` + ``close``) только он сам, в ``finally`` после
выхода из цикла: единственный вызывающий ``_release``, поэтому остановка и аварийный
выход не закроют прибор дважды, а ``close`` не пойдёт под идущим ``get_frame``
(на Windows закрытие не будит блокирующий вызов, а буфер кадра освобождается).
Отказ на ``start_grabbing`` закрывает handle в ``start()`` — поток там ещё не создан.
Режим съёмки (``trigger=``) пишется в прибор между ``open`` и ``start_grabbing`` (при идущем
захвате узлы закрыты ``0x80020106``), а возвращается в том же ``_release`` — между
``stop_grabbing`` и ``close``; отказ узла не роняет ``start()`` и живёт в ``param_errors``.
``stop()`` лишь поднимает событие и ждёт поток ``timeout + timeout_ms``: дедлайн
держится на собственном таймауте ``get_frame``.

Автопереподключения нет (решение 6 плана): после трёх ошибок ``get_frame`` подряд
прибор закрывается, состояние ``error``, дальше — ``stop()``/``start()`` снаружи.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
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

# Режим съёмки: ключ рецепта -> (узел GenICam, тип, родительский узел). Порядок — порядок записи:
# источник и период недоступны (0x80020106), пока не записан родитель.
_TRIGGER_NODES: dict[str, tuple[str, str, str | None]] = {
    "trigger_mode": ("TriggerMode", "enum", None),
    "trigger_source": ("TriggerSource", "enum", "TriggerMode"),
    "trigger_period_ms": ("TriggerSelfTriggerPeriod", "int", "TriggerSource"),
}
_SKIPPED = "пропущен: родитель не записан"


def _exc_text(exc: BaseException) -> str:
    """Текст исключения вместе с ``__notes__``: ``str(exc)`` заметки не включает
    (так терялся код отказа DestroyHandle, приложенный к ошибке OpenDevice)."""
    return "; ".join([str(exc), *getattr(exc, "__notes__", ())])


@dataclass
class _Session:
    """Одно открытие прибора: handle и своё событие остановки (у задержавшегося потока — своё)."""

    handle: Any
    stop: threading.Event = field(default_factory=threading.Event)
    # Записанные при старте узлы режима съёмки: (узел, тип, исходное значение) в порядке записи.
    restore: list[tuple[str, str, int]] = field(default_factory=list)
    # time.monotonic() события stop() — для замера «от stop до начала возврата»; None, если поток остановился сам.
    stop_at: float | None = None


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
        trigger: Mapping[str, Any] | None = None,
    ) -> None:
        if api is None:
            from Services.code_reader.sdk.api import MvCodeReaderApi

            api = MvCodeReaderApi()  # DLL грузится лениво, на первом вызове
        self._api = api
        self._on_frame = on_frame
        self._on_error = on_error
        self._device_ip = device_ip
        self._timeout_ms = int(timeout_ms)
        self._trigger = self._parse_trigger(trigger)

        self._life = threading.Lock()  # сериализует start()/stop(); SDK-вызовы открытия идут под ним
        self._lock = threading.Lock()  # короткий: состояние и счётчики
        self._session: _Session | None = None
        self._thread: threading.Thread | None = None

        self._state = "stopped"
        self._device: dict[str, str] | None = None
        self._last_error: str | None = None
        self._counts = {"frames": 0, "ok": 0, "no_code": 0, "bad_code": 0, "errors": 0}
        # Узел режима съёмки -> почему не записан. Не ошибка сессии: в `errors`/`last_error` не попадает.
        self._param_errors: dict[str, str] = {}

    @staticmethod
    def _parse_trigger(trigger: Mapping[str, Any] | None) -> list[tuple[str, str, Any, str | None]]:
        """Заданные поля режима -> [(узел, тип, значение, родитель)] в порядке записи. ``""``/``0`` = не трогать."""
        trigger = trigger or {}
        unknown = sorted(set(trigger) - set(_TRIGGER_NODES))
        if unknown:
            raise ValueError(f"неизвестные ключи trigger: {unknown}; допустимы {list(_TRIGGER_NODES)}")
        plan = []
        for key, (node, kind, parent) in _TRIGGER_NODES.items():
            value = trigger.get(key)
            if value is None or value == "" or value == 0:
                continue
            plan.append((node, kind, value, parent))
        return plan

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
                session.stop_at = time.monotonic()
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
                "param_errors": dict(self._param_errors),
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

        with self._lock:
            self._param_errors = {}

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

        # Режим съёмки пишется строго до start_grabbing: при идущем захвате узлы закрыты (0x80020106).
        # Любой выход из блока (отказ start_grabbing, непредвиденное исключение) возвращает записанное
        # и закрывает handle; stop_grabbing там не зовётся — захват не начинался.
        restore: list[tuple[str, str, int]] = []
        try:
            self._apply_trigger(handle, entry.ip, restore)
            self._api.start_grabbing(handle)
        except BaseException as exc:
            try:
                self._restore_trigger(handle, restore, messages)
            finally:  # close при ЛЮБОМ выходе из возврата (в т.ч. KeyboardInterrupt): handle не утекает
                try:
                    self._api.close(handle)
                except Exception as close_exc:
                    messages.append(self._note_error(f"close после отказа StartGrabbing: {_exc_text(close_exc)}"))
            if not isinstance(exc, Exception):
                raise
            messages.append(self._fail_open(entry, exc))
            return False

        session = _Session(handle, restore=restore)
        with self._lock:
            self._device = {"ip": entry.ip, "model": entry.model, "serial": entry.serial}
            self._state = "running"
        self._session = session
        self._thread = threading.Thread(target=self._run, args=(session,), name="code-reader-sdk", daemon=True)
        self._thread.start()
        return True

    def _apply_trigger(self, handle: Any, ip: str, restore: list[tuple[str, str, int]]) -> None:
        """Записать режим съёмки: на узел — прочитать исходное, записать, запомнить для возврата.

        ``restore`` наполняется на месте, чтобы при любом выходе вызывающий вернул то, что успело записаться.
        Отказ узла (любое исключение) — в ``param_errors`` и WARNING; ``errors``/``last_error``/``on_error`` не трогаем.
        """
        in_recipe = {node for node, _, _, _ in self._trigger}
        written: set[str] = set()
        for node, kind, value, parent in self._trigger:
            if parent in in_recipe and parent not in written:
                self._node_failed(node, _SKIPPED)
                continue
            try:
                if kind == "enum":
                    read, write = self._api.get_enum, self._api.set_enum_str
                else:
                    read, write = self._api.get_int, self._api.set_int
                original = read(handle, node)["cur"]
                if original is None:
                    raise ValueError("исходное значение узла не прочиталось")
                # До записи: если возврат откажет, оператор вернёт прибор руками по этой строке.
                _log.info("code_reader SDK [%s]: %s: %s -> %s", ip, node, original, value)
                write(handle, node, value)
            except Exception as exc:
                # Не-SdkError: только имя типа, в str(exc) может быть значение из рецепта.
                text = f"0x{exc.code:08X}: {exc.where}" if isinstance(exc, SdkError) else type(exc).__name__
                self._node_failed(node, text)
                continue
            restore.append((node, kind, original))
            written.add(node)

    def _node_failed(self, node: str, text: str) -> None:
        with self._lock:
            self._param_errors[node] = text
        _log.warning("code_reader SDK: режим съёмки, узел %s не записан: %s", node, text)

    def _restore_trigger(self, handle: Any, restore: list[tuple[str, str, int]], failures: list[str]) -> None:
        """Вернуть записанные узлы в обратном порядке, каждый в своём ``try``.

        Тексты отказов (уже учтённых ``_note_error``) дописываются в ``failures`` на месте — их эмитит вызывающий
        ПОСЛЕ ``close``. ``BaseException`` одного узла не мешает остальным: пробуются все, затем он пробрасывается.
        Длительность каждой записи — в INFO-лог (``возврат <узел> мс=``): опыт на приборе по причине отказов возврата.
        """
        fatal: BaseException | None = None
        for node, kind, original in reversed(restore):
            started = time.monotonic()
            _log.info("code_reader SDK: возврат %s -> %s", node, original)
            outcome = "ok"
            try:
                (self._api.set_enum if kind == "enum" else self._api.set_int)(handle, node, original)
            except Exception as exc:
                outcome = "отказ"
                # Значение в тексте: после отказа оператор вернёт его руками.
                failures.append(self._note_error(f"возврат {node} -> {original}: {_exc_text(exc)}"))
            except BaseException as exc:
                outcome = "прервано"
                fatal = fatal or exc
            finally:
                _log.info("code_reader SDK: возврат %s мс=%d (%s)", node, (time.monotonic() - started) * 1000, outcome)
        if fatal is not None:
            raise fatal

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
        """``stop_grabbing``, возврат режима съёмки, ``close``. Зовётся только из ``finally`` потока захвата.

        Возврат пробуется всегда (и после упавшего ``stop_grabbing``) и строго до ``close``; ``close`` — всегда.
        Колбэк ``on_error`` (``_emit``) зовётся ПОСЛЕ ``close``: зависший или упавший колбэк не держит прибор.
        """
        messages: list[str] = []
        try:
            started = time.monotonic()
            try:
                self._api.stop_grabbing(session.handle)
            except Exception as exc:
                messages.append(self._note_error(f"stop_grabbing: {_exc_text(exc)}"))
            finally:
                _log.info("code_reader SDK: stop_grabbing мс=%d", (time.monotonic() - started) * 1000)
            if session.restore:
                since = "н/д" if session.stop_at is None else f"{(time.monotonic() - session.stop_at) * 1000:.0f}"
                _log.info("code_reader SDK: возврат режима, от stop() до начала мс=%s", since)
            self._restore_trigger(session.handle, session.restore, messages)
        finally:
            try:
                self._api.close(session.handle)
            except Exception as exc:
                messages.append(self._note_error(f"close: {_exc_text(exc)}"))
            for message in messages:
                self._emit(message)

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
