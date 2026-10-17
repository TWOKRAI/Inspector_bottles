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

# Счётчики ok / no_code / bad_code на момент кадра (с учётом reset_stats) — для строки статуса overlay.
type _Counters = tuple[int, int, int]


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
        trigger = {
            key: value
            for key in ("trigger_mode", "trigger_source", "trigger_period_ms")
            if (value := getattr(self._reg, key))
        }
        if trigger:
            reader_kwargs["trigger"] = trigger
        self._reader: SdkCodeReader = type(self).reader_factory(self._on_frame, self._on_error, **reader_kwargs)
        ctx.log_info(
            f"CodeReaderSdkPlugin[{self._reg.reader_id}]: configured "
            f"(прибор {self._reg.device_ip or 'первый найденный'}, таймаут {self._reg.timeout_ms} мс)"
        )

    def start(self, ctx: PluginContext) -> None:
        """Взять прибор, если задан автозахват; иначе ждать команды из GUI."""
        if self._reg.auto_start:
            self.cmd_take_device({})
        else:
            self._publish_state()

    def shutdown(self, ctx: PluginContext) -> None:
        """Остановить захват и отпустить прибор."""
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
    # Команды из GUI
    # ------------------------------------------------------------------ #

    def cmd_take_device(self, data: dict) -> dict:
        """Взять прибор и начать захват. Отказ — `status: error` с причиной, не исключение."""
        # Старую причину стираем ДО start(): поток захвата может сбоить раньше, чем вернётся
        # start(), и его ошибка (через `_on_error`) уже принадлежит новой сессии.
        with self._lock:
            self._last_error = ""
        ok = self._reader.start()
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
