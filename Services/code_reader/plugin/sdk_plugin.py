# -*- coding: utf-8 -*-
"""CodeReaderSdkPlugin — source-плагин «кадр и коды с прибора через MvCodeReader SDK».

В отличие от TCP-плагина (`plugin.py`, приём порта) здесь прибор берётся
эксклюзивно: `SdkCodeReader` держит handle и крутит захват в своём потоке. Каждое
срабатывание — один item с кодами и серой картинкой кадра.

Разделение потоков:
    поток захвата (SdkCodeReader) → `_on_frame` → очередь SdkFrame
    поток источника (SourceProducer) → `produce()` → декод + items наружу

Форма item совместима с TCP-плагином (плоские `code`, `status`, `ts`, `seq_id`,
`reader_id`), сверху — `codes`, `trigger_index`, `frame_num`, `no_read_num`,
`pixel_format` и `frame` (uint8 H×W). Картинка едет ТОЛЬКО под ключом `frame`:
claim check в SHM видит только его; JPEG-байты или отрисованный кадр под другим
ключом пошли бы через 64 КБ pipe. `data_type` плагин не ставит — его проставит
SourceProducer при наличии кадра.

`produce()` никогда не блокирует (контракт source-плагина, как у TCP-плагина).
Автопереподключения нет (решение 6 плана): `on_error` только публикует состояние и
`start()` не зовёт; вернуть прибор — команда `take_device`.

Слой: Services → framework. Плагин не импортирует `Plugins` и `multiprocess_prototype`.
"""

from __future__ import annotations

import functools
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, ClassVar

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from Services.code_reader.core.result import ReadStatus
from Services.code_reader.core.sdk_frame import SdkFrame, decode_image
from Services.code_reader.core.sdk_reader import SdkCodeReader

from .sdk_registers import CodeReaderSdkRegisters

# Глубина очереди между потоком захвата и produce(). Переполнение = pipeline стоит;
# старые кадры теряем (каждый несёт JPEG), потеря видна в `dropped`, а не молча.
_QUEUE_LIMIT = 8

# Сколько последних срабатываний держать в истории для GUI.
_HISTORY_LIMIT = 20

_STILL_HELD = "прибор ещё отпускается"

# Поля режима съёмки и узлы прибора, которым они соответствуют (ключи дублируют `sdk_reader._TRIGGER_NODES`:
# плагин не лезет в приватное читателя). Живая правка этих полей перезапускает захват (`_on_trigger_update`).
_TRIGGER_FIELD_NODES = {
    "trigger_mode": "TriggerMode",
    "trigger_source": "TriggerSource",
    "trigger_period_ms": "TriggerSelfTriggerPeriod",
}
_TRIGGER_FIELDS = tuple(_TRIGGER_FIELD_NODES)
_TRIGGER_NODES = frozenset(_TRIGGER_FIELD_NODES.values())
# Префикс `last_error` режима съёмки: такую причину снимает только `_sync_health`, не take_device.
_TRIGGER_ERROR = "trigger apply:"
# Захват после неудачной правки не идёт: литерал для журнала и `last_error`.
_RETAKE = "захват остановлен, возьмите прибор заново"
_NOT_RUNNING = "прежний режим не запущен"
# Части причины о том, что захват не идёт: после удачного `_take` они неверны. Порядок важен: сначала с «;».
_NOT_RUNNING_TAILS = (f"; {_NOT_RUNNING}", f"; {_RETAKE}", f" {_RETAKE}")

# Счётчики ok / no_code / bad_code на момент кадра (с учётом reset_stats) — для строки статуса overlay.
type _Counters = tuple[int, int, int]


def _trigger_from(values: dict[str, Any]) -> dict[str, Any]:
    """Режим съёмки для читателя: только непустые поля из `_TRIGGER_FIELDS` (пусто / 0 = «не трогать»)."""
    return {key: value for key in _TRIGGER_FIELDS if (value := values.get(key))}


def _refusal_text(refused: dict[str, str]) -> str:
    return "; ".join(f"{node}: {text}" for node, text in refused.items())


@register_plugin(
    "code_reader_sdk",
    category="source",
    description="Промышленный считыватель кодов Hikrobot ID3000 (кадр и коды через MvCodeReader SDK)",
)
class CodeReaderSdkPlugin(ProcessModulePlugin):
    """Источник кадров с кодами.

    Команды:
        take_device    — взять прибор и начать захват
        release_device — остановить захват и отпустить прибор
        get_status     — полная телеметрия
        reset_stats    — сбросить счётчики и историю
    """

    name = "code_reader_sdk"
    category = "source"

    register_class = CodeReaderSdkRegisters

    inputs: list[Port] = []
    outputs: list[Port] = [
        Port(
            name="code",
            dtype="str",
            shape="-",
            description="Текст первого читаемого кода срабатывания (пусто, если кода нет)",
        ),
        Port(
            name="frame",
            dtype="image/gray",
            shape="(H, W)",
            optional=True,
            description="Картинка кадра uint8; нет, если JPEG не декодировался",
        ),
        Port(
            name="overlay",
            dtype="dict",
            shape="-",
            optional=True,
            description="Draw-params для overlay_draw: рамки кодов, подписи, строка статуса со счётчиками",
        ),
    ]

    commands: dict[str, str] = {
        "take_device": "cmd_take_device",
        "release_device": "cmd_release_device",
        "get_status": "cmd_get_status",
        "reset_stats": "cmd_reset_stats",
    }

    # Шов для тестов: читается в configure() через тип, тест подменяет атрибут класса
    # на functools.partial(SdkCodeReader, api=FakeApi(...)).
    reader_factory: ClassVar[Callable[..., SdkCodeReader]] = SdkCodeReader

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """Прочитать register и создать читатель (прибор берётся в start()/take_device)."""
        self._ctx = ctx
        # Подписки на поля триггера (`_subscribe_trigger`). getattr, а не `[]`: повторный configure обязан увидеть
        # прежние, иначе `_unsubscribe_trigger` их не снимет и колбэк удвоится. Первой строкой: `shutdown` зовут и
        # после configure, бросившего на полпути.
        self._trigger_subscriptions: list[tuple[Any, str, Callable[[Any], None]]] = getattr(
            self, "_trigger_subscriptions", []
        )
        self._reg: CodeReaderSdkRegisters = self._init_register(ctx)
        # (seq, ts, кадр, счётчики ok/no/bad на момент этого кадра — для строки статуса overlay).
        self._queue: deque[tuple[int, float, SdkFrame, _Counters]] = deque(maxlen=_QUEUE_LIMIT)
        self._history: deque[dict] = deque(maxlen=_HISTORY_LIMIT)
        self._lock = threading.Lock()  # состояние плагина; читатель под ним НЕ зовём
        self._seq = 0
        self._last_quality: dict | None = None
        self._decode_errors = 0
        # Единственный источник причины сбоя: все ошибки читателя (и отказ start()) приходят
        # в `_on_error`; сюда же — отказ декода и «ещё отпускается». Читателя не опрашиваем.
        self._last_error = ""
        # Плохие подписи `labels` (проверка один раз, здесь): отдельное поле, чтобы take_device и reset_stats
        # его не стирали; в `last_error` попадает, пока нет настоящей ошибки захвата.
        self._labels_error = _check_labels(self._reg.labels)
        if self._labels_error:
            ctx.log_error(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: плохие подписи labels: {self._labels_error}")
        self._overlay_error_logged = False  # ERROR про отказ overlay пишем один раз на плагин
        # `device_held`, ушедший в дерево в последний раз: produce() публикует при смене.
        self._published_held = False
        # Сериализует «снимок → merge → отметка» между потоками захвата, источника и команд:
        # иначе устаревший снимок одного потока ложится в дерево поверх свежего и отметка
        # врёт (ревью 6.3 итерации 2, п.3: дерево застревало с device_held True). Под ним
        # берутся только короткие замки (читателя и self._lock), держатели которых сюда не ходят.
        self._publish_lock = threading.Lock()
        # Счётчики читателя не сбрасываются — reset_stats запоминает точку отсчёта.
        self._baseline = {"frames": 0, "ok": 0, "no_code": 0, "bad_code": 0, "errors": 0}
        reader_kwargs: dict[str, Any] = {
            "device_ip": self._reg.device_ip or None,
            "timeout_ms": self._reg.timeout_ms,
        }
        # Режим съёмки: только непустые поля; нет ни одного — читатель создаётся без `trigger`.
        trigger = _trigger_from({key: getattr(self._reg, key) for key in _TRIGGER_FIELDS})
        # Режим следующего (или идущего) сеанса: читатель получает его в `_take`, когда поток захвата мёртв. Он же
        # цель отката при отказе живой правки. Меняется только под `_trigger_lock`.
        self._applied_trigger: dict[str, Any] = trigger
        self._want_grab = False  # намерение оператора: удачный `_take` ставит, release / shutdown снимают
        self._closed = False  # после shutdown колбэк правки не делает ничего
        # Отказы узлов режима последнего сеанса, где захват запустился: неудачный `start()` стирает `param_errors`
        # читателя, а «отказывал до правки» должно переживать такой отказ. Пишет только `_take`.
        self._session_refusals: dict[str, str] = {}
        # Сериализует take_device / release_device / shutdown и колбэк живой правки триггера: колбэк идёт в потоке
        # системного вызывающего `set_field_value` и держит его на остановку и открытие. Колбэки читателя замок
        # не берут (проверено: они зовут только `_on_frame` / `_on_error`), замок не реентерабелен.
        self._trigger_lock = threading.Lock()
        if trigger:
            reader_kwargs["trigger"] = trigger
        self._reader: SdkCodeReader = type(self).reader_factory(self._on_frame, self._on_error, **reader_kwargs)
        ctx.log_info(
            f"CodeReaderSdkPlugin[{self._reg.reader_id}]: configured "
            f"(прибор {self._reg.device_ip or 'первый найденный'}, таймаут {self._reg.timeout_ms} мс)"
        )
        self._subscribe_trigger()

    def start(self, ctx: PluginContext) -> None:
        """Взять прибор, если задан автозахват; иначе ждать команды из GUI."""
        if self._reg.auto_start:
            self.cmd_take_device({})
        else:
            self._publish_state()

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановить захват и отпустить прибор.

        Подписку снимаем первой; идущий колбэк живой правки дорабатывает до конца (остановка ждёт `_trigger_lock`),
        новый после снятия не придёт, а пришедший раньше увидит остановленный читатель только после своего конца.
        """
        self._unsubscribe_trigger()
        with self._trigger_lock:
            self._closed = True
            self._want_grab = False
            self._reader.stop()
            self._publish_state()
            ctx.log_info(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: shutdown")

    # ------------------------------------------------------------------ #
    # Поток данных
    # ------------------------------------------------------------------ #

    def produce(self) -> list[dict]:
        """Слить очередь в items и декодировать картинки. Пусто — норма, не ошибка.

        Не блокирует: кадры приходят из потока захвата, ждать их здесь нельзя.
        """
        with self._lock:
            batch = list(self._queue)
            self._queue.clear()
        items: list[dict] = []
        for seq, ts, frame, counters in batch:
            item = self._build_item(seq, ts, frame, counters)
            # ponytail: декод в produce() — до 8 JPEG за проход (~до 100 мс). Если линия
            # быстрее, перенести декод в поток захвата или ограничить число кадров на проход.
            try:
                item["frame"] = decode_image(frame)
            except Exception as exc:  # noqa: BLE001 — код важнее картинки: item уходит без кадра
                self._on_decode_error(frame, exc)
            items.append(item)
        # Публикуем то, что принесли кадры. Смена состояния и ошибки публикуются из своих
        # колбэков: они происходят и когда кадров нет. Исключение — выход потока захвата после
        # позднего release_device: колбэка у него нет, о смене `device_held` узнаём здесь.
        # Читатель опрашиваем без замка плагина (у него свой короткий замок).
        held_changed = bool(self._reader.stats()["device_held"]) != self._published_held
        if items or held_changed:
            self._publish_state()
        return items

    def _build_item(self, seq: int, ts: float, frame: SdkFrame, counters: _Counters) -> dict:
        code = _first_readable(frame)
        return {
            "code": "" if code is None else code.text,
            "status": frame.status.value,
            "ts": ts,
            "seq_id": seq,
            "reader_id": self._reg.reader_id,
            "codes": [c.to_dict() for c in frame.codes],
            "trigger_index": frame.trigger_index,
            "frame_num": frame.frame_num,
            "no_read_num": frame.no_read_num,
            "pixel_format": frame.pixel_format,
            "overlay": self._safe_overlay(frame, counters),
        }

    def _safe_overlay(self, frame: SdkFrame, counters: _Counters) -> dict[str, Any]:
        """``_overlay`` без права уронить ``produce()``: очередь уже слита, падение потеряло бы всю пачку кадров.

        Отказ -> пустой overlay и ОДИН ERROR на плагин (не на кадр).
        """
        try:
            return _overlay(frame, counters, self._reg.labels)
        except Exception as exc:  # noqa: BLE001 — кадр с кодом важнее подписей
            if not self._overlay_error_logged:
                self._overlay_error_logged = True
                self._ctx.log_error(
                    f"CodeReaderSdkPlugin[{self._reg.reader_id}]: overlay не построен ({type(exc).__name__}); "
                    "кадры идут без подписей и рамок, повторы не пишутся"
                )
            return {"lines": [], "points": []}

    def _on_frame(self, frame: SdkFrame) -> None:
        """Колбэк читателя. Вызывается в потоке захвата, не в source.

        Очередь, счётчик `seq`, `dropped` и история меняются под одним `self._lock`:
        поток захвата и `produce()` работают одновременно.
        """
        now = time.time()
        code = _first_readable(frame)
        # Читатель считает кадр ДО колбэка, поэтому его счётчики уже включают этот кадр. Снимок —
        # здесь, а не в produce(): пачка из нескольких кадров иначе получила бы одни и те же числа.
        # Читателя зовём вне self._lock (как в _snapshot).
        stats = self._reader.stats()
        with self._lock:
            base = self._baseline
            # max(0, ...): reset_stats между снимком и замком даст базу новее снимка — не показываем минус.
            counters: _Counters = (
                max(0, stats["ok"] - base["ok"]),
                max(0, stats["no_code"] - base["no_code"]),
                max(0, stats["bad_code"] - base["bad_code"]),
            )
            self._seq += 1
            overflow = len(self._queue) == _QUEUE_LIMIT
            self._queue.append((self._seq, now, frame, counters))
            self._history.append(
                {
                    "code": "" if code is None else code.text,
                    "status": frame.status.value,
                    "ts": now,
                    "trigger_index": frame.trigger_index,
                }
            )
            if overflow:
                self._reg.dropped += 1
            self._reg.last_status = frame.status.value
            if code is not None:
                self._reg.last_code = code.text
                self._last_quality = None if code.quality is None else code.quality.to_dict()
        # Переполнение = `produce()` не сливает очередь, публикации от него в этом
        # состоянии не будет — сообщаем о потере сразу.
        if overflow:
            self._publish_state()

    def _on_error(self, message: str) -> None:
        """Колбэк читателя: ошибка захвата или смена состояния. Только публикуем.

        `start()` отсюда НЕ зовём: автопереподключения нет (решение 6 плана), на
        финальном сбое читатель всё равно ответил бы отказом.
        """
        with self._lock:
            self._last_error = message
        self._ctx.log_error(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: {message}")
        self._publish_state()

    def _on_decode_error(self, frame: SdkFrame, exc: Exception) -> None:
        message = f"кадр trigger={frame.trigger_index}: картинка не декодирована: {exc}"
        with self._lock:
            self._decode_errors += 1
            self._last_error = message
        self._ctx.log_error(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: {message}")

    # ------------------------------------------------------------------ #
    # Состояние
    # ------------------------------------------------------------------ #

    def _snapshot(self) -> dict[str, Any]:
        """Телеметрия для дерева и `get_status`. `device_state` — всегда из читателя.

        Читатель опрашиваем ДО `self._lock`: под ним читателя не зовём, иначе колбэк
        потока захвата (ему нужен этот замок) сцепился бы с вызовом в читатель.
        """
        stats = self._reader.stats()
        reg = self._reg
        with self._lock:
            base = self._baseline
            device_held = bool(stats["device_held"])
            last_error = self._last_error
            # «ещё отпускается» — производное от device_held: поток вышел -> сообщение снято.
            if last_error == _STILL_HELD and not device_held:
                last_error = ""
            if not last_error:
                last_error = self._labels_error
            # register — зеркало для GUI, читают отсюда только при показе.
            reg.device_state = stats["state"]
            reg.total_reads = stats["ok"] - base["ok"]
            reg.no_reads = stats["no_code"] - base["no_code"]
            reg.bad_reads = stats["bad_code"] - base["bad_code"]
            reg.frames = stats["frames"] - base["frames"]
            reg.errors = stats["errors"] - base["errors"] + self._decode_errors
            reg.last_error = last_error
            # `.get`: подставные читатели старых тестов отдают stats() без ключа.
            param_errors = "; ".join(f"{node}: {text}" for node, text in (stats.get("param_errors") or {}).items())
            reg.param_errors = param_errors
            return {
                "device_state": reg.device_state,
                "device": stats["device"],
                "device_held": device_held,
                "last_code": reg.last_code,
                "last_status": reg.last_status,
                "last_quality": self._last_quality,
                "total_reads": reg.total_reads,
                "no_reads": reg.no_reads,
                "bad_reads": reg.bad_reads,
                "frames": reg.frames,
                "errors": reg.errors,
                "dropped": reg.dropped,
                "last_error": last_error,
                "param_errors": param_errors,
                "pending": len(self._queue),
                "history": list(self._history),
            }

    def _publish_state(self) -> None:
        """Опубликовать телеметрию в реактивное дерево (живой GUI).

        Зовётся там, где состояние изменилось: из `on_error`, при переполнении, из
        команд и из `produce()`, когда пришли кадры или сменился `device_held`.

        Отметку `_published_held` ставим только здесь, после записи в дерево: `_snapshot`
        зовёт и `get_status`, который не публикует, — отметка оттуда «съедала» бы смену
        (тест `test_status_poll_does_not_swallow_release_for_tree`).
        """
        proxy = getattr(self._ctx, "state_proxy", None)
        if proxy is None:
            return
        try:
            with self._publish_lock:
                snapshot = self._snapshot()
                proxy.merge(f"processes.{self._ctx.process_name}.state.code_reader_sdk", snapshot)
                self._published_held = snapshot["device_held"]
        except Exception as exc:  # noqa: BLE001 — публикация телеметрии не критична
            self._ctx.log_error(f"CodeReaderSdkPlugin: публикация состояния не удалась: {exc}")

    # ------------------------------------------------------------------ #
    # Живая правка режима съёмки (W1-b)
    # ------------------------------------------------------------------ #

    def _subscribe_trigger(self) -> None:
        """Подписка на поля режима съёмки; прежние подписки плагина снимаются (повторный `configure`)."""
        self._unsubscribe_trigger()
        registers = self._ctx.registers
        if registers is None:
            self._ctx.log_warning(
                f"CodeReaderSdkPlugin[{self._reg.reader_id}]: нет RegistersManager, живая правка триггера отключена"
            )
            return
        for field in _TRIGGER_FIELDS:
            callback = functools.partial(self._on_trigger_update, field)  # свой объект на поле и на configure
            registers.subscribe(self.name, field, callback)
            self._trigger_subscriptions.append((registers, field, callback))

    def _unsubscribe_trigger(self) -> None:
        """Снять подписки `_subscribe_trigger`; повторный вызов — пустая операция."""
        subscriptions, self._trigger_subscriptions = self._trigger_subscriptions, []
        for registers, field, callback in subscriptions:  # менеджер тот, на котором подписались
            registers.unsubscribe(self.name, field, callback)

    def _on_trigger_update(self, field: str, value: Any) -> None:
        """Колбэк подписки (поток вызывающего `set_field_value`): применить правку режима съёмки. Не бросает.

        Решает НАМЕРЕНИЕ, а не живость потока: захват нужен оператору (`_want_grab`) -> остановка и новый `_take`;
        не нужен -> значение только запоминается в `_applied_trigger` и войдёт в следующий `_take`. После
        `shutdown` колбэк не делает ничего. Откат на прежний режим — если отказал узел изменённого поля или узел,
        который в прошлом сеансе не отказывал; старый отказ чужого узла правку не блокирует. Поток захвата не
        вышел в срок -> повторов нет, оператору сказано взять прибор заново. Здоровье снимает только
        `_sync_health`. Колбэк держит поток вызывающего до остановки и открытия; параллельный `take_device`
        ждёт `_trigger_lock`. Значения поля в журнал и `last_error` не попадают.
        """
        head = f"CodeReaderSdkPlugin[{self._reg.reader_id}]: apply field={field} policy=restart"
        with self._trigger_lock:
            if self._closed:  # колбэк, отданный в доставку до отписки
                return
            old = self._applied_trigger
            restarting = False
            try:
                new = _trigger_from({**{key: getattr(self._reg, key) for key in _TRIGGER_FIELDS}, field: value})
                if new == old:
                    self._ctx.log_info(f"{head} restarted=False: значение не изменило режим")
                    self._sync_health()
                    return
                if not self._want_grab:
                    self._applied_trigger = new
                    self._ctx.log_info(
                        f"{head} restarted=False: захват не идёт, значение войдёт в следующий take_device"
                    )
                    self._publish_state()
                    return
                previous = self._session_refusals
                restarting = True
                if not self._stop_grab():
                    # Поздний get_frame: `set_trigger` на живом потоке не зовём, режим войдёт в следующий take_device.
                    self._applied_trigger = new
                    self._ctx.log_error(f"{head} restarted=False: захват не остановился в срок; {_RETAKE}")
                    self._mark_apply_failed(field, f"{_TRIGGER_ERROR} field={field} {_RETAKE}")
                    return
                self._applied_trigger = new
                result = self._take(report=False)
                if result["status"] == "ok":
                    # `start()` отвечает True и при отказе узла режима: причина живёт в `param_errors`.
                    refused = self._trigger_refusals()
                    if _TRIGGER_FIELD_NODES[field] not in refused and set(refused) <= set(previous):
                        if refused:
                            self._ctx.log_warning(
                                f"{head} restarted=True applied=True param_errors={_refusal_text(refused)} "
                                "(эти узлы отказывали и до правки)"
                            )
                            self._replace_mode_error(refused)
                        else:
                            self._ctx.log_info(f"{head} restarted=True applied=True")
                        self._sync_health()
                        return
                    text = _refusal_text(refused)
                    # Первая причина — ДО отката: он длится до дедлайна остановки и может не дойти до конца.
                    self._ctx.log_error(
                        f"CodeReaderSdkPlugin[{self._reg.reader_id}]: режим не принят прибором: "
                        f"field={field} applied=False param_errors={text}"
                    )
                    running = self._fall_back(old)
                    tail = "" if running else f"; {_RETAKE}"
                    self._ctx.log_error(
                        f"{head} restarted=True applied=False param_errors={text} fallback=old ok={running}{tail}"
                    )
                    self._mark_apply_failed(field, f"{_TRIGGER_ERROR} field={field} applied=False{tail}")
                else:
                    error = result.get("error", "")
                    running = self._fall_back(old)
                    tail = "" if running else f"; {_RETAKE}"
                    self._ctx.log_error(f"{head} restarted=False error={error} fallback=old ok={running}{tail}")
                    self._mark_apply_failed(
                        field,
                        f"{_TRIGGER_ERROR} field={field} restarted=False; "
                        f"{'прежний режим идёт' if running else _NOT_RUNNING}{tail}",
                    )
            except Exception as exc:  # noqa: BLE001 — колбэк идёт в системном потоке процесса: наружу не выпускается
                self._applied_trigger = old
                ok: bool | str = self._fall_back(old) if restarting else "-"
                tail = f"; {_RETAKE}" if ok is False else ""
                self._ctx.log_error(f"{head} отказ: {type(exc).__name__} ok={ok}{tail}")
                self._mark_apply_failed(field, f"{_TRIGGER_ERROR} field={field} отказ: {type(exc).__name__}{tail}")

    def _trigger_refusals(self) -> dict[str, str]:
        """Отказы узлов режима съёмки в сеансе читателя (`.get`: подставные читатели старых тестов без ключа)."""
        errors = self._reader.stats().get("param_errors") or {}
        return {node: text for node, text in errors.items() if node in _TRIGGER_NODES}

    def _stop_grab(self) -> bool:
        """`stop()` читателя. True — поток захвата вышел: только тогда можно менять режим и открывать прибор."""
        self._reader.stop()
        return not self._reader.stats()["device_held"]

    def _fall_back(self, old: dict[str, Any]) -> bool:
        """Вернуть прежний режим и захват. Под `_trigger_lock`. Не бросает; True — захват идёт."""
        self._applied_trigger = old
        try:
            return self._stop_grab() and self._take(report=False)["status"] == "ok"
        except Exception as exc:  # noqa: BLE001 — отказ отката не должен скрыть первую причину
            self._ctx.log_warning(
                f"CodeReaderSdkPlugin[{self._reg.reader_id}]: откат режима не удался: {type(exc).__name__}"
            )
            return False

    def _replace_mode_error(self, refused: dict[str, str]) -> None:
        """Правка применена, остались только старые отказы: прежняя причина режима называет уже применённое поле.

        Меняет только имеющуюся причину режима на список отказавших узлов; деградацию не трогает.
        """
        with self._lock:
            stale = self._last_error.startswith(_TRIGGER_ERROR)
            if stale:
                self._last_error = f"{_TRIGGER_ERROR} param_errors={_refusal_text(refused)}"
        if stale:
            self._publish_state()

    def _drop_not_running_tails(self) -> None:
        """Захват пошёл: в причине режима остаётся только факт расхождения (регистр не равен прибору).

        Деградацию не трогает; публикует вызывающий (`_take`).
        """
        with self._lock:
            if self._last_error.startswith(_TRIGGER_ERROR):
                for tail in _NOT_RUNNING_TAILS:
                    self._last_error = self._last_error.replace(tail, "")

    def _sync_health(self) -> None:
        """Снять деградацию по ФАКТАМ; зовётся под `_trigger_lock` после правки и после `_take`.

        Здорово = захват идёт, в его сеансе нет отказов узлов режима и режим из регистра равен `_applied_trigger`.
        Только тогда `health.set_status("ok")` и снятие `last_error` режима съёмки; иначе не снимается ничего.
        Прибор отпущен оператором (или не брался) -> здоровье не трогается.
        """
        if not self._want_grab or self._reader.stats()["state"] != "running" or self._trigger_refusals():
            return
        if _trigger_from({key: getattr(self._reg, key) for key in _TRIGGER_FIELDS}) != self._applied_trigger:
            return
        self._ctx.health.set_status("ok")
        with self._lock:
            stale = self._last_error.startswith(_TRIGGER_ERROR)
            if stale:
                self._last_error = ""
        if stale:
            self._publish_state()

    def _mark_apply_failed(self, field: str, last_error: str) -> None:
        """Режим в приборе не тот, что просили: деградация процесса, `last_error`, публикация.

        `last_error` пишется ПОСЛЕ `_take`. Деградацию (заявка этого плагина) и эту причину снимает только
        `_sync_health`. Значения поля в тексте нет. Строку ERROR пишет вызывающий: сюда не входит ни один разъём
        журнала (правило «один разъём на точку»).
        """
        self._ctx.health.degraded(f"code_reader: trigger apply field={field}")
        with self._lock:
            self._last_error = last_error
        self._publish_state()

    # ------------------------------------------------------------------ #
    # Команды из GUI
    # ------------------------------------------------------------------ #

    def cmd_take_device(self, data: dict) -> dict:
        """Взять прибор и начать захват. Отказ — `status: error` с причиной, не исключение."""
        with self._trigger_lock:
            return self._take()

    def _take(self, *, report: bool = True) -> dict:
        """Тело `take_device`; зовётся под `_trigger_lock` (команда и колбэк живой правки).

        Поток захвата мёртв -> читатель получает `_applied_trigger` ДО `start()` (единственное место). `report` —
        сказать об отказах узлов нового сеанса (ERROR, degraded, `last_error`); колбэк правки говорит сам.
        """
        fresh = not self._reader.stats()["device_held"]
        if fresh:
            self._reader.set_trigger(self._applied_trigger or None)
        # Старую причину стираем ДО start(): поток захвата может сбоить раньше, чем вернётся
        # start(), и его ошибка (через `_on_error`) уже принадлежит новой сессии. Причину режима съёмки
        # стирает только `_sync_health`.
        with self._lock:
            if not self._last_error.startswith(_TRIGGER_ERROR):
                self._last_error = ""
        ok = self._reader.start()
        if ok:
            self._want_grab = True
            self._drop_not_running_tails()
            self._session_refusals = self._trigger_refusals()
            refused = self._session_refusals if report and fresh else {}
            if refused:
                text = _refusal_text(refused)
                self._ctx.log_error(
                    f"CodeReaderSdkPlugin[{self._reg.reader_id}]: режим съёмки, узлы не записаны: param_errors={text}"
                )
                self._ctx.health.degraded("code_reader: trigger param_errors")
                with self._lock:
                    self._last_error = f"{_TRIGGER_ERROR} take_device: param_errors={text}"
            self._sync_health()
        self._publish_state()
        snapshot = self._snapshot()
        result: dict[str, Any] = {"status": "ok" if ok else "error", "device_state": snapshot["device_state"]}
        if not ok:
            result["error"] = snapshot["last_error"]
        return result

    def cmd_release_device(self, data: dict) -> dict:
        """Остановить захват и отпустить прибор.

        Отпускает прибор поток захвата, а не эта команда: при позднем `get_frame` (или
        вызове из колбэка) прибор ещё удерживается, и об этом сказано прямо.
        """
        with self._trigger_lock:
            return self._release()

    def _release(self) -> dict:
        """Тело `release_device`; зовётся под `_trigger_lock`."""
        self._want_grab = False  # оператор отпустил: правка прибор не захватывает, даже если поток ещё жив
        self._ctx.log_info(f"CodeReaderSdkPlugin[{self._reg.reader_id}]: прибор ОТПУСТИТЬ")
        self._reader.stop()
        held = bool(self._reader.stats()["device_held"])
        if held:
            with self._lock:
                self._last_error = _STILL_HELD
        self._publish_state()
        result: dict[str, Any] = {"status": "error" if held else "ok", "released": not held, "device_held": held}
        if held:
            result["error"] = _STILL_HELD
        return result

    def cmd_get_status(self, data: dict) -> dict:
        """Полная телеметрия."""
        return {
            "status": "ok",
            "reader_id": self._reg.reader_id,
            **self._snapshot(),
        }

    def cmd_reset_stats(self, data: dict) -> dict:
        """Сбросить счётчики и историю (наладка стенда)."""
        stats = self._reader.stats()
        reg = self._reg
        with self._lock:
            self._history.clear()
            self._baseline = {k: stats[k] for k in self._baseline}
            self._decode_errors = 0
            self._last_error = ""
            self._last_quality = None
            reg.dropped = 0
            reg.last_code = reg.last_status = ""
        self._publish_state()
        return {"status": "ok"}

    def get_status(self) -> dict[str, Any]:
        """Статус для внешнего опроса (та же форма, что у команды)."""
        return self.cmd_get_status({})


def _overlay(frame: SdkFrame, counters: _Counters, labels: list[dict[str, Any]]) -> dict[str, Any]:
    """Draw-params для `overlay_draw` (форма — README `Plugins/render/overlay_draw`).

    Чистая функция: только dict/list/int/str, без bytes и numpy — проходит `json.dumps`.
    Цветов здесь нет: фигуры несут `group`, цвет и размер по группе задаёт `color_table` узла `overlay_draw`
    (в рецепте). На каждый код — замкнутая рамка из отрезков `corners[i] -> corners[(i+1) % n]` в группе
    `code_ok` / `code_bad`. Подписи — из регистра `labels` (любое число), см. `_label_point`.
    """
    lines: list[dict[str, Any]] = []
    codes = []
    for code in frame.codes:
        corners = [list(p) for p in code.corners]
        if not corners:
            continue
        codes.append((code, corners))
        group = "code_ok" if code.status is ReadStatus.OK else "code_bad"
        if len(corners) > 1:
            for i, p1 in enumerate(corners):
                lines.append({"p1": p1, "p2": corners[(i + 1) % len(corners)], "group": group})

    ok, no_code, bad_code = counters
    base_vars = {
        "status": frame.status.value,
        "ok": ok,
        "no": no_code,
        "bad": bad_code,
        "total": ok + no_code + bad_code,
    }
    first = _first_readable(frame)
    frame_state = "ok" if frame.status is ReadStatus.OK else "bad"
    points: list[dict[str, Any]] = []
    for spec in labels:
        if not isinstance(spec, dict):
            continue
        if spec.get("per", "frame") == "code":
            for code, corners in codes:
                text = code.text if code.status is ReadStatus.OK else code.status.value
                state = "ok" if code.status is ReadStatus.OK else "bad"
                point = _label_point(spec, {**base_vars, "code": text, "state": state}, corners)
                if point is not None:
                    points.append(point)
        else:
            frame_vars = {**base_vars, "code": "" if first is None else first.text, "state": frame_state}
            point = _label_point(spec, frame_vars, [])
            if point is not None:
                points.append(point)
    return {"lines": lines, "points": points}


def _format(template: Any, values: dict[str, Any]) -> str:
    """str.format по шаблону из рецепта; опечатка в шаблоне видна на кадре как есть, а не роняет produce().

    ``TypeError`` — например ``{ok[0]}`` (индекс у числа); ``OverflowError`` — ``{ok:c}`` при ``ok >= 1114112``.
    Ловится любое ``Exception``: подпись обязана остаться, ``produce()`` не падает.
    """
    try:
        return str(template).format(**values)
    except Exception:  # noqa: BLE001 — шаблон из рецепта, любой отказ format = показать шаблон как есть
        return str(template)


_PER_VALUES = ("frame", "code")
_ANCHOR_VALUES = ("frame", "corner0")


class _BadLabelField(ValueError):
    """Поле подписи, на котором строгий расчёт упал: ``field`` и имя типа исключения (без значения из рецепта)."""

    def __init__(self, field: str, exc_name: str) -> None:
        super().__init__(f"{field} {exc_name}")
        self.field = field
        self.exc_name = exc_name


# Предел координаты: cv2.putText кладёт текст в xy+6 и падает на int32
# (замер: (2**31-1, 0) -> error, (2**30-10, 0) рисуется).
_COORD_LIMIT = 2**30
# Потолок scale: время putText растёт квадратично (замер, кадр 1280x1024: 50 -> 32 мс, 100 -> 119 мс,
# 1000 -> 12,6 с), а толщина round(scale*2.5) на 1e9 выходит за int32.
_SCALE_MAX = 50.0


def _in_coord_range(value: float) -> bool:
    # Без math.isfinite: на целом >= 2**1024 он бросает OverflowError; для nan/inf сравнение само даёт False.
    return -_COORD_LIMIT <= value < _COORD_LIMIT


def _number(value: Any, field: str) -> float:
    """Конечное число в пределах int32 (не bool, не строка) или ``_BadLabelField``."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _BadLabelField(field, "TypeError")
    if not _in_coord_range(value):
        raise _BadLabelField(field, "ValueError")
    return value


def _label_point_strict(
    spec: dict[str, Any], values: dict[str, Any], corners: list[list[int]]
) -> dict[str, Any] | None:
    """Одна подпись как точка overlay: ``xy`` = якорь + (dx, dy). Якорь ``corner0`` без углов — подписи нет.

    Строгая: плохое поле (нечисловые ``dx``/``dy``/``scale``, ``xy`` не пара чисел) даёт ``_BadLabelField``.
    Единственный путь расчёта: ``_label_point`` (для кадров) и ``_check_labels`` (один раз в configure) зовут её.
    """
    if spec.get("per", "frame") not in _PER_VALUES:
        raise _BadLabelField("per", "ValueError")
    anchor = spec.get("anchor", "corner0" if spec.get("per") == "code" else "frame")
    if anchor not in _ANCHOR_VALUES:
        raise _BadLabelField("anchor", "ValueError")
    if anchor == "corner0":
        if not corners:
            return None
        bx, by = corners[0]
    else:
        try:
            bx, by = spec.get("xy", (0, 0))
        except (TypeError, ValueError) as exc:
            raise _BadLabelField("xy", type(exc).__name__) from None
        bx, by = _number(bx, "xy"), _number(by, "xy")
    dx, dy = _number(spec.get("dx", 0), "dx"), _number(spec.get("dy", 0), "dy")
    xy = [int(round(bx + dx)), int(round(by + dy))]  # слагаемые уже конечные и в int32
    if not all(_in_coord_range(v) for v in xy):
        raise _BadLabelField("xy", "ValueError")  # сумма вышла за int32
    point: dict[str, Any] = {"xy": xy, "label": _format(spec.get("template", ""), values)}
    if spec.get("group"):
        point["group"] = _format(spec["group"], values)
    if "scale" in spec:
        raw_scale = spec["scale"]
        if isinstance(raw_scale, bool):
            raise _BadLabelField("scale", "TypeError")
        try:
            scale = float(raw_scale)
        except (TypeError, ValueError, OverflowError) as exc:
            raise _BadLabelField("scale", type(exc).__name__) from None
        if not -_SCALE_MAX <= scale <= _SCALE_MAX:  # nan / inf (в т.ч. из строки "nan") тоже не проходят
            raise _BadLabelField("scale", "ValueError")
        point["scale"] = scale
    return point


def _label_point(spec: dict[str, Any], values: dict[str, Any], corners: list[list[int]]) -> dict[str, Any] | None:
    """Подпись для кадра; плохая подпись пропускается (``None``), остальные подписи и кадры идут.

    Без лога на каждый кадр: о плохих подписях оператору сказал ``_check_labels`` в ``configure``.
    """
    try:
        return _label_point_strict(spec, values, corners)
    except (TypeError, ValueError):
        return None


def _check_labels(labels: Any) -> str:
    """Сухой прогон строгого расчёта по каждой подписи: ``labels[1]: dx TypeError; labels[2]: scale ValueError``.

    Пусто — всё в порядке. Значения из рецепта в текст не попадают, только индекс, поле и имя типа исключения.
    """
    problems: list[str] = []
    for index, spec in enumerate(labels if isinstance(labels, list) else []):
        if not isinstance(spec, dict):
            problems.append(f"labels[{index}]: не dict ({type(spec).__name__})")
            continue
        dummy_corners = [[0, 0]] if spec.get("per", "frame") == "code" else []
        try:
            _label_point_strict(spec, {}, dummy_corners)
        except _BadLabelField as exc:
            problems.append(f"labels[{index}]: {exc.field} {exc.exc_name}")
        except (TypeError, ValueError) as exc:  # непредвиденное поле: хотя бы имя типа
            problems.append(f"labels[{index}]: {type(exc).__name__}")
    return "; ".join(problems)


def _first_readable(frame: SdkFrame):
    """Первая читаемая запись кода кадра или None."""
    return next((c for c in frame.codes if c.status is ReadStatus.OK), None)
