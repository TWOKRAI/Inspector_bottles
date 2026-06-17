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
        Port(name="pick_xy", dtype="dict", optional=True, description="{x_mm,y_mm} забор с ленты (от pixel_to_robot)"),
        Port(name="return_trigger", dtype="any", optional=True, description="Сигнал «вернуть всё на ленту» (пульт)"),
    ]
    outputs = [
        Port(name="robot_job", dtype="dict", optional=True, description="Поза укладки {pick_*, place_*, e_capture}"),
        Port(
            name="robot_return_jobs",
            dtype="list[dict]",
            optional=True,
            description="Список поз возврата выложенных букв на ленту",
        ),
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
        # Латч слова: слово приходит ОДНИМ item (сигнал пульта/телефона), распознавание —
        # другими items (без слова). Держим последнее непустое, пока не придёт новое.
        self._latched_word = ""
        # Детект «нового диска»: новый диск = сменилась буква ИЛИ была пауза (нет диска).
        # Дедуп по БУКВЕ (не углу — угол дрожит на ±1-2° и плодил бы ложные «новые диски»).
        self._armed = True
        self._settle = 0
        self._cur_label = ""
        # Триггер-режим: взвод по сигналу trigger.
        self._trig_armed = False
        # Возврат: фронт сигнала «вернуть на ленту» (срабатывает раз на нажатие).
        self._return_armed = True
        # Once-флаг предупреждения «нет калибровки/pick» (не флудить лог).
        self._warned_no_pick = False
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

        # ВОЗВРАТ: сигнал с пульта → вернуть ВСЕ выложенные буквы на ленту, затем сброс.
        # Проверяем ДО done-выхода — возврат возможен и после готового слова.
        ret = self._maybe_return(item)
        if ret is not None:
            return ret

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

        # Координата ЗАБОРА с ленты (из калибровки pixel_to_robot). Без неё робот не
        # сможет взять диск → при require_pick слот не съедаем (раскладка не desync'ится).
        pick = self._resolve_pick(item)
        if pick is None and self._reg.require_pick:
            self._note_no_pick()
            return item

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

        # Команда роботу: ЗАБОР (pick с ленты, трекинг по энкодеру) + УКЛАДКА (place в слот
        # слова) + доворот r (angle_zero − угол модели). z — высота укладки (register).
        pose = {
            "place_x_mm": job["x_mm"],
            "place_y_mm": job["y_mm"],
            "place_z_mm": float(self._reg.place_z_mm),
            "place_rz_deg": job["angle_deg"],
            "char": job["char"],
            "slot": job["slot"],
            "raw_angle_deg": job["raw_angle_deg"],
        }
        if pick is not None:
            pose["pick_x_mm"] = pick[0]
            pose["pick_y_mm"] = pick[1]
            pose["pick_z_mm"] = float(self._reg.pick_z_mm)
            e_cap = item.get(self._reg.encoder_source)
            if e_cap is not None:
                pose["e_capture"] = int(e_cap)
        self._reg.jobs_emitted += 1
        self._reg.slots_filled = self._assembler.filled_count
        self._reg.last_correction_deg = round(float(job["angle_deg"]), 2)
        self._reg.next_letter = self._assembler.next_letter
        self._reg.done = self._assembler.done
        pick_txt = f"взять({pick[0]:.1f},{pick[1]:.1f}) → " if pick else ""
        self._ctx.log_info(
            f"WordLayoutPlugin: слот {job['slot']} '{job['char']}' → {pick_txt}положить "
            f"x{pose['place_x_mm']:.1f} y{pose['place_y_mm']:.1f} z{pose['place_z_mm']:.1f} "
            f"r{pose['place_rz_deg']:.1f}° [{self._reg.slots_filled}/{self._reg.slots_total}]"
        )
        return {**item, self._reg.job_key: pose}

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _resolve_word(self, item: dict) -> str:
        """Слово: входной порт (приоритет) → латч последнего → register «Слово».

        Слово приходит ОДНИМ item (сигнал пульта signal_2 / телефон), а распознавание —
        другими items (без слова). Латчим последнее непустое слово и держим его, пока не
        придёт новое — иначе target_word терялся бы на следующем же кадре предсказаний.
        """
        src = self._reg.word_source
        if src:
            w = item.get(src)
            if isinstance(w, dict):
                w = w.get("word") or w.get("value") or ""
            if isinstance(w, str) and w.strip():
                self._latched_word = w
                return w
        return self._latched_word or self._reg.target_word

    def _resolve_pick(self, item: dict) -> tuple[float, float] | None:
        """Координата забора с ленты (мм робота) из item[pick_source] = {x_mm, y_mm}."""
        p = item.get(self._reg.pick_source)
        if isinstance(p, dict) and "x_mm" in p and "y_mm" in p:
            self._warned_no_pick = False
            return float(p["x_mm"]), float(p["y_mm"])
        return None

    def _note_no_pick(self) -> None:
        """Лог раз на переход: нет координаты забора (обычно не загружена калибровка)."""
        if not self._warned_no_pick:
            self._ctx.log_info(
                "WordLayoutPlugin: нет pick_xy (калибровка?) — диск не беру, слот не занимаю "
                "(require_pick=True). Прогони визард / поставь require_pick=False для демо без робота"
            )
            self._warned_no_pick = True

    # ------------------------------------------------------------------ #
    # ВОЗВРАТ на ленту
    # ------------------------------------------------------------------ #

    def _maybe_return(self, item: dict) -> dict | None:
        """Сигнал «вернуть на ленту» → задания возврата всех заполненных слотов + сброс.

        Срабатывает на ФРОНТЕ сигнала (раз на нажатие): сигнал приходит одним item
        (кнопка пульта/телефона, ключ = имя исходного порта), держим взвод между сигналами.
        Возвращаем то, что РЕАЛЬНО выложено (заполненные слоты) — даже если слово не готово.
        После выдачи — сброс раскладки (можно вводить новое слово; робот доедет очередь сам).
        """
        src = self._reg.return_trigger_source
        if not src:
            return None
        fired = item.get(src)
        if fired is None or fired is False:
            self._return_armed = True  # сигнала нет → взвестись на следующий
            return None
        if not self._return_armed:
            return None  # тот же сигнал ещё держится — не повторяем
        self._return_armed = False

        jobs = self._build_return_jobs()
        if not jobs:
            self._ctx.log_info("WordLayoutPlugin: сигнал возврата, но возвращать нечего (нет выложенных)")
            return None

        self._ctx.log_info(f"WordLayoutPlugin: возврат {len(jobs)} букв на ленту → сброс раскладки")
        self._assembler.reset()
        self._reg.slots_filled = 0
        self._reg.done = False
        self._reg.next_letter = self._assembler.next_letter
        # Раскладка взводится заново для нового слова.
        self._armed = True
        self._settle = 0
        self._cur_label = ""
        return {**item, self._reg.return_jobs_key: jobs}

    def _build_return_jobs(self) -> list[dict]:
        """Позы возврата для всех заполненных слотов: координата слота + Z (откуда забрать)."""
        jobs: list[dict] = []
        for idx, s in enumerate(self._assembler.slots):
            if s.filled:
                jobs.append(
                    {
                        "x_mm": s.x_mm,
                        "y_mm": s.y_mm,
                        "z_mm": float(self._reg.place_z_mm),
                        "slot": idx,
                        "char": s.char,
                    }
                )
        return jobs

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
