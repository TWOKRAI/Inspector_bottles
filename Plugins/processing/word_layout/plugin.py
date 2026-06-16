"""WordLayoutPlugin — планировщик раскладки слова для робота-сортировщика.

Конвейер: диск едет по ленте → ml_inference распознаёт букву+угол → этот плагин
жадно кладёт диск в первый незаполненный слот целевого слова и выдаёт роботу
задание ``{x_mm, y_mm, angle_deg}`` (куда положить и на сколько довернуть). Реальный
доворот в прошивке робота — follow-up; пока угол едет в задании, укладка по (x,y)
работает через robot_io уже сейчас.

Вход: ``predictions`` (от ml_inference) + опц. ``word`` (слово) + опц. ``trigger``.
Выход: ``robot_job`` (dict) — вяжется к ``robot_io.job_source``; кадр пробрасывается.
"""

from __future__ import annotations

import time

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from . import geometry
from .assembler import Slot, WordAssembler
from .registers import WordLayoutRegisters

# Период публикации прогресса в state, сек.
_PUBLISH_PERIOD_S = 1.0


@register_plugin(
    "word_layout",
    category="processing",
    description="Раскладка слова: буква+угол (ml_inference) → задание роботу {x_mm,y_mm,angle_deg} по слотам",
)
class WordLayoutPlugin(ProcessModulePlugin):
    """predictions → потоковый жадный матчинг → robot_job по слотам слова."""

    name = "word_layout"
    category = "processing"
    thread_safe = False

    inputs = [
        Port(
            name="predictions",
            dtype="list[dict]",
            shape="N",
            description="Топ-K от ml_inference: label, confidence, angle_deg, angle_valid",
        ),
        Port(name="word", dtype="any", optional=True, description="Целевое слово (строка/dict); иначе register"),
        Port(name="trigger", dtype="any", optional=True, description="Сигнал «взять диск» (если use_trigger)"),
    ]
    outputs = [
        Port(name="robot_job", dtype="dict", optional=True, description="{x_mm, y_mm, angle_deg, char, slot}"),
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", optional=True, description="Кадр (pass-through)"),
    ]

    commands: dict[str, str] = {"reset_word": "cmd_reset"}
    register_class = WordLayoutRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import WordLayoutPluginConfig

        return WordLayoutPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: WordLayoutRegisters = self._init_register(ctx)
        self._state_proxy = ctx.state_proxy

        self._assembler: WordAssembler | None = None
        self._sig: tuple | None = None  # подпись (слово+геометрия) — пересборка при смене
        # Детект «нового диска»: новый диск = сменилась буква ИЛИ была пауза (нет диска).
        # Дедуп по БУКВЕ (не углу — угол дрожит на ±1-2° и плодил бы ложные «новые диски»).
        self._armed = True
        self._settle = 0
        self._cur_label = ""
        # Триггер-режим: взвод по сигналу trigger.
        self._trig_armed = False
        self._last_publish = time.monotonic()

        ctx.log_info(f"WordLayoutPlugin: configured (word='{self._reg.target_word}')")

    # ------------------------------------------------------------------ #
    # КОМАНДА — сбросить раскладку (начать слово заново)
    # ------------------------------------------------------------------ #

    def cmd_reset(self, _data: dict) -> dict:
        """Сбросить заполнение слотов (начать раскладку заново)."""
        if self._assembler is not None:
            self._assembler.reset()
            self._reg.slots_filled = 0
            self._reg.done = False
            self._reg.next_letter = self._assembler.next_letter
        self._armed = True
        self._settle = 0
        self._cur_label = ""
        self._ctx.log_info("WordLayoutPlugin: раскладка сброшена")
        return {"status": "ok"}

    # ------------------------------------------------------------------ #
    # PROCESS
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        out: list[dict] = []
        for item in items:
            out.append(self._handle_item(item))

        now = time.monotonic()
        if now - self._last_publish >= _PUBLISH_PERIOD_S:
            self._publish_state()
            self._last_publish = now
        return out

    def _handle_item(self, item: dict) -> dict:
        word = self._resolve_word(item)
        if not word.strip():
            return item
        self._ensure_assembler(word)
        assert self._assembler is not None
        if self._assembler.done:
            self._reg.done = True
            return item

        # Триггер-режим: сигнал на порту взводит однократный взвод.
        if self._reg.use_trigger and self._reg.trigger_source:
            trig = item.get(self._reg.trigger_source)
            if trig is not None and trig is not False:
                self._trig_armed = True

        pred = self._top_pred(item)
        if not self._should_take(pred):
            return item
        assert pred is not None

        self._reg.last_label = pred["label"]
        self._reg.last_angle_deg = round(float(pred["angle_deg"]), 2)
        job = self._assembler.offer(
            pred["label"],
            pred["angle_deg"],
            pred["angle_valid"],
            zero_deg=float(self._reg.angle_zero_deg),
            sign=-1.0 if self._reg.angle_invert else 1.0,
        )
        if job is None:
            # Буква не нужна/дубль — диск пропускаем (взвод снят, ждём следующий).
            return item

        # Команда роботу: полная поза перемещения x, y, z, r (доворот). z — высота
        # укладки (register), r — доворот до общей ориентации (angle_zero − угол модели).
        pose = {
            "x_mm": job["x_mm"],
            "y_mm": job["y_mm"],
            "z_mm": float(self._reg.place_z_mm),
            "r_deg": job["angle_deg"],
            "char": job["char"],
            "slot": job["slot"],
            "raw_angle_deg": job["raw_angle_deg"],
        }
        self._reg.jobs_emitted += 1
        self._reg.slots_filled = self._assembler.filled_count
        self._reg.last_correction_deg = round(float(job["angle_deg"]), 2)
        self._reg.next_letter = self._assembler.next_letter
        self._reg.done = self._assembler.done
        self._ctx.log_info(
            f"WordLayoutPlugin: слот {job['slot']} '{job['char']}' → "
            f"x{pose['x_mm']:.1f} y{pose['y_mm']:.1f} z{pose['z_mm']:.1f} r{pose['r_deg']:.1f}° "
            f"[{self._reg.slots_filled}/{self._reg.slots_total}]"
        )
        return {**item, self._reg.job_key: pose}

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _resolve_word(self, item: dict) -> str:
        """Слово из входного порта (приоритет) или из register «Слово»."""
        src = self._reg.word_source
        if src:
            w = item.get(src)
            if isinstance(w, dict):
                w = w.get("word") or w.get("value") or ""
            if isinstance(w, str) and w.strip():
                return w
        return self._reg.target_word

    def _build_assembler(self, word: str) -> tuple[WordAssembler, list[geometry.Point]]:
        """Собрать матчер по текущему режиму раскладки (шаг от первого / между first-last)."""
        cells = geometry.parse_word(word, int(self._reg.word_gap_slots))
        first = (self._reg.first_x, self._reg.first_y)
        if self._reg.use_pitch:
            pitch = float(self._reg.pitch_mm) or 2.0 * float(self._reg.disk_radius_mm)
            positions = geometry.pitch_positions(first, self._reg.line_angle_deg, pitch, cells)
        else:
            positions = geometry.slot_positions(first, (self._reg.last_x, self._reg.last_y), cells)
        letters = [c for c in cells if c is not None]
        slots = [Slot(ch, x, y) for ch, (x, y) in zip(letters, positions)]
        return WordAssembler(slots), positions

    def _ensure_assembler(self, word: str) -> None:
        """Пересобрать матчер при смене слова или геометрии линии."""
        sig = (
            word,
            self._reg.use_pitch,
            self._reg.first_x,
            self._reg.first_y,
            self._reg.line_angle_deg,
            self._reg.pitch_mm,
            self._reg.last_x,
            self._reg.last_y,
            self._reg.disk_radius_mm,
            self._reg.word_gap_slots,
        )
        if sig == self._sig:
            return
        self._sig = sig
        self._assembler, positions = self._build_assembler(word)
        self._reg.word_norm = "".join(s.char for s in self._assembler.slots)
        self._reg.slots_total = self._assembler.total
        self._reg.slots_filled = 0
        self._reg.next_letter = self._assembler.next_letter
        self._reg.done = False
        self._reg.spacing_warn = geometry.min_spacing(positions) < 2.0 * float(self._reg.disk_radius_mm)
        # Новое слово — взвестись заново.
        self._armed = True
        self._settle = 0
        self._cur_label = ""
        if self._reg.spacing_warn:
            self._ctx.log_info(
                f"WordLayoutPlugin: ВНИМАНИЕ — слоты теснее диаметра диска "
                f"({2.0 * self._reg.disk_radius_mm:.0f} мм), диски могут наложиться"
            )

    def _top_pred(self, item: dict) -> dict | None:
        """Топ-1 уверенное предсказание (label/angle_deg/angle_valid) или None."""
        preds = item.get(self._reg.predictions_source)
        if not isinstance(preds, list) or not preds:
            return None
        top = preds[0]
        if not isinstance(top, dict) or not top.get("label"):
            return None
        if float(top.get("confidence", 1.0)) < float(self._reg.min_confidence):
            return None
        return {
            "label": str(top["label"]),
            "angle_deg": float(top.get("angle_deg", 0.0)),
            "angle_valid": bool(top.get("angle_valid", False)),
        }

    def _should_take(self, pred: dict | None) -> bool:
        """Брать ли этот диск сейчас. Триггер-режим — по сигналу; авто — новый диск.

        Авто: «новый диск» = сменилась буква ИЛИ перед ним была пауза (нет диска).
        Дедуп по букве защищает от повтора одного диска во многих кадрах (непрерывный
        тракт); смена буквы взводит сразу (триггерный тракт даёт ~1 кадр на диск, без
        пауз между разными буквами). settle_frames>1 — подавить разовый misread
        (ОСТОРОЖНО: в тракте «1 кадр на диск» ставь 1, иначе диск не возьмётся).
        """
        if self._reg.use_trigger:
            if self._trig_armed and pred is not None:
                self._trig_armed = False
                return True
            return False

        # Пауза (нет диска/слабый) → взвестись, ждать следующий диск.
        if pred is None:
            self._armed = True
            self._settle = 0
            self._cur_label = ""
            return False
        # Сменилась буква → новый диск: взвестись и начать счёт стабильности заново.
        if pred["label"] != self._cur_label:
            self._cur_label = pred["label"]
            self._settle = 1
            self._armed = True
        else:
            self._settle += 1
        if not self._armed:
            return False
        if self._settle >= max(1, int(self._reg.settle_frames)):
            # Берём диск один раз; до прихода другой буквы/паузы повторно не берём.
            self._armed = False
            self._settle = 0
            return True
        return False

    def _publish_state(self) -> None:
        """Опубликовать прогресс раскладки в StateStore (для дашборда/дисплея)."""
        if self._state_proxy is None:
            return
        self._state_proxy.merge(
            f"processes.{self._ctx.process_name}.state.word_layout",
            {
                "word": self._reg.word_norm,
                "slots_total": self._reg.slots_total,
                "slots_filled": self._reg.slots_filled,
                "next_letter": self._reg.next_letter,
                "last_label": self._reg.last_label,
                "last_angle_deg": self._reg.last_angle_deg,
                "last_correction_deg": self._reg.last_correction_deg,
                "jobs_emitted": self._reg.jobs_emitted,
                "done": self._reg.done,
                "spacing_warn": self._reg.spacing_warn,
            },
        )

    def shutdown(self, ctx: PluginContext) -> None:
        ctx.log_info(
            f"WordLayoutPlugin: shutdown (выдано {self._reg.jobs_emitted}, "
            f"заполнено {self._reg.slots_filled}/{self._reg.slots_total})"
        )
