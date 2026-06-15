"""MLInferencePlugin — тонкий processing-плагин инференса нейросети.

Тяжёлая логика (загрузка модели, backend, pre/post) живёт в Services.ml_inference.engine.
Плагин лишь связывает pipeline с движком: кадр → engine.predict → predictions (+ overlay).

Слой Services → framework. Плагин не импортирует prototype/Plugins.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    register_plugin,
)

from Services.ml_inference.engine import InferenceEngine

from .registers import MLInferenceRegisters

# Services/ml_inference/plugin/plugin.py → parents[3] = корень проекта.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MODELS_DIR = _PROJECT_ROOT / "data" / "models"

logger = logging.getLogger(__name__)

# Кириллица в overlay: cv2.putText (Hershey) не рисует кириллицу → '???'.
# Рисуем через PIL TTF. Шрифт грузится один раз (ленивая инициализация).
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
_FONT: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None


def _overlay_font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    global _FONT
    if _FONT is None:
        for path in _FONT_CANDIDATES:
            if Path(path).is_file():
                _FONT = ImageFont.truetype(path, 22)
                break
        else:
            _FONT = ImageFont.load_default()
    return _FONT


def _put_text_unicode(frame_bgr: np.ndarray, text: str, org: tuple[int, int], color=(0, 255, 0)) -> np.ndarray:
    """Нарисовать текст (в т.ч. кириллицу) на BGR-кадре через PIL. Цвет — BGR."""
    img = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    ImageDraw.Draw(img).text(org, text, font=_overlay_font(), fill=(color[2], color[1], color[0]))
    frame_bgr[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    return frame_bgr


@register_plugin(
    "ml_inference",
    category="processing",
    description="Инференс нейросети (кадр → классы + confidence)",
)
class MLInferencePlugin(ProcessModulePlugin):
    """Инференс изображения через подключаемый backend (ONNX/torch)."""

    name = "ml_inference"
    category = "processing"

    # InferenceSession не thread-safe. process() фреймворк зовёт последовательно
    # (один поток pipeline_executor), НО команды (set_model/reload) приходят на
    # ДРУГОМ потоке (message_processor) и могут пересоздать сессию во время predict.
    # thread_safe фреймворком не enforce'ится → защищаемся сами через _engine_lock.
    thread_safe = False

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Кадр (опц. overlay)"),
        Port(name="predictions", dtype="list[dict]", shape="N", description="Топ-K: class_id, label, confidence"),
    ]

    commands = {
        "set_model": "cmd_set_model",
        "set_threshold": "cmd_set_threshold",
        "reload_model": "cmd_reload_model",
    }

    register_class = MLInferenceRegisters

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        """Создать движок, загрузить выбранную модель (если задана)."""
        self._ctx = ctx
        self._reg: MLInferenceRegisters = self._init_register(ctx)
        self._state_proxy = ctx.state_proxy

        models_dir = ctx.config.get("models_dir") or str(_DEFAULT_MODELS_DIR)
        self._engine = InferenceEngine(models_dir)
        # Сериализует доступ к движку: predict() (поток pipeline_executor) против
        # load/unload из команд (поток message_processor) — иначе гонка по сессии.
        self._engine_lock = threading.Lock()

        # Кэш для inference_every_n + телеметрия latency.
        self._frame_idx: int = 0
        self._last_predictions: list[dict] = []
        self._latency_sum_ms: float = 0.0
        self._latency_count: int = 0
        self._last_latency_ms: float = 0.0  # мгновенное значение последнего инференса
        self._max_latency_ms: float = 0.0  # худший спайк за окно публикации
        self._last_publish: float = time.monotonic()

        self._load_selected_model()
        ctx.log_info(
            f"MLInferencePlugin: configured (model='{self._reg.model}', "
            f"device={self._reg.device}, каталог={models_dir})"
        )

    def shutdown(self, ctx: PluginContext) -> None:
        """Выгрузить модель и освободить ресурсы."""
        self._engine.unload()
        ctx.log_info("MLInferencePlugin: shutdown")

    # ------------------------------------------------------------------ #
    # Обработка
    # ------------------------------------------------------------------ #

    def process(self, items: list[dict]) -> list[dict]:
        """Прогнать кадры через движок. Pass-through если модель не выбрана/не готова."""
        out: list[dict] = []
        for item in items:
            result = self._process_item(item)
            if result is not None:
                out.append(result)

        now = time.monotonic()
        elapsed = now - self._last_publish
        if elapsed >= 1.0:
            self._publish_state(elapsed)
            self._last_publish = now
        return out

    def _process_item(self, item: dict) -> dict | None:
        """Один кадр → predictions (+ overlay)."""
        frame = item.get("frame")
        if frame is None:
            return None

        # Модель не выбрана/движок не готов → честный pass-through (не падаем).
        if not self._reg.model or not self._engine.is_ready:
            return {**item, "predictions": []}

        every_n = max(1, self._reg.inference_every_n)
        self._frame_idx += 1
        run_now = (self._frame_idx % every_n) == 0 or not self._last_predictions

        if run_now:
            t0 = time.monotonic()
            try:
                # lock: команда set_model/reload на другом потоке может в этот момент
                # выгружать/пересоздавать сессию (engine.load_model → unload → _session=None)
                with self._engine_lock:
                    preds = self._engine.predict(
                        frame,
                        top_k=self._reg.top_k,
                        threshold=self._reg.confidence_threshold,
                    )
            except Exception as exc:  # noqa: BLE001 — кадр не должен ронять процесс
                self._reg.last_error = str(exc)
                self._ctx.log_error(f"MLInferencePlugin: ошибка инференса: {exc}")
                logger.exception("MLInferencePlugin: inference error")  # traceback в лог
                return {**item, "predictions": []}
            # успешный инференс снимает прошлую транзиентную ошибку (иначе stale-«красный»
            # висит в телеметрии до перезагрузки модели)
            if self._reg.last_error:
                self._reg.last_error = ""
            dt_ms = (time.monotonic() - t0) * 1000
            self._latency_sum_ms += dt_ms
            self._latency_count += 1
            self._last_latency_ms = dt_ms
            self._max_latency_ms = max(self._max_latency_ms, dt_ms)
            self._last_predictions = preds
            self._update_last_pred_telemetry(preds)
        else:
            preds = self._last_predictions

        result_frame = frame
        if self._reg.draw_overlay and preds:
            result_frame = self._draw_overlay(frame.copy(), preds[0])

        # overlay пишем в 'frame' (его читает дисплей; SHM-middleware стрипует
        # именно 'frame'). Отдельный 'rendered_frame' НЕ заводим — он поехал бы
        # полным кадром через pickle на каждом кадре (грабли line_filter).
        return {**item, "frame": result_frame, "predictions": preds}

    @staticmethod
    def _draw_overlay(frame, top1: dict):
        """Топ-1 класс + confidence + угол (если определён) поверх кадра.

        Угол: angle_valid=True → «θ°»; есть angle_deg, но valid=False (full-симметрия)
        → «любой» (доворот не нужен). Кириллица рисуется через PIL.
        """
        text = f"{top1['label']} {top1['confidence']:.2f}"
        if top1.get("angle_valid"):
            text += f"  {top1['angle_deg']:.0f}°"
        elif "angle_deg" in top1:
            text += "  ∠любой"
        return _put_text_unicode(frame, text, (8, 6), (0, 255, 0))

    # ------------------------------------------------------------------ #
    # Команды (live)
    # ------------------------------------------------------------------ #

    def cmd_set_model(self, data: dict) -> dict:
        """Сменить модель в runtime (выгрузка старой + загрузка новой)."""
        model = data.get("model", "")
        self._reg.model = model
        if "device" in data:
            self._reg.device = data["device"]
        self._load_selected_model()
        return {"status": "ok", "loaded_model": self._reg.loaded_model, "error": self._reg.last_error}

    def cmd_set_threshold(self, data: dict) -> dict:
        """Обновить порог/top_k без перезагрузки модели."""
        for field in ("confidence_threshold", "top_k", "inference_every_n", "draw_overlay"):
            if field in data:
                setattr(self._reg, field, data[field])
        return {"status": "ok"}

    def cmd_reload_model(self, _data: dict) -> dict:
        """Перезагрузить текущую модель (например, после замены файла весов)."""
        self._engine.registry.scan()
        self._load_selected_model()
        return {"status": "ok", "loaded_model": self._reg.loaded_model, "error": self._reg.last_error}

    # ------------------------------------------------------------------ #
    # Внутреннее
    # ------------------------------------------------------------------ #

    def _load_selected_model(self) -> None:
        """Загрузить self._reg.model в движок; ошибки → last_error (не падаем)."""
        self._reg.last_error = ""
        # Сбросить кэш предсказаний/счётчик кадров — иначе при inference_every_n > 1
        # первые кадры после смены модели вернут результаты предыдущей модели.
        self._last_predictions = []
        self._frame_idx = 0
        # сбросить угловую телеметрию — у новой модели может не быть angle_head
        self._reg.last_angle_deg = 0.0
        self._reg.last_angle_valid = False
        self._reg.active_providers = ""
        # lock: не пересоздавать сессию, пока predict() на другом потоке её читает
        with self._engine_lock:
            if not self._reg.model:
                self._engine.unload()
                self._reg.loaded_model = ""
                return
            try:
                self._engine.load_model(self._reg.model, device=self._reg.device)
                self._reg.loaded_model = self._engine.current_model or self._reg.model
                # фактические providers (показывает молчаливый CPU-fallback при device=cuda)
                self._reg.active_providers = ", ".join(self._engine.active_providers)
            except Exception as exc:  # noqa: BLE001 — нет модели не должно ронять процесс
                self._reg.last_error = str(exc)
                self._reg.loaded_model = ""
                self._ctx.log_error(f"MLInferencePlugin: не удалось загрузить '{self._reg.model}': {exc}")

    def _update_last_pred_telemetry(self, preds: list[dict]) -> None:
        """Обновить readonly-поля последнего предсказания (класс + угол).

        При пустом результате / отсутствии угла у top-1 СБРАСЫВАЕМ angle_valid И
        обнуляем сам угол/класс — иначе в телеметрии висит фантом прошлого объекта
        (число last_angle_deg выглядит валидным), и неаккуратный потребитель,
        читающий угол без проверки angle_valid, довернул бы по stale-значению.
        """
        if not preds:
            self._reg.last_label = ""
            self._reg.last_confidence = 0.0
            self._reg.last_angle_deg = 0.0
            self._reg.last_angle_valid = False
            return
        top = preds[0]
        self._reg.last_label = top["label"]
        self._reg.last_confidence = round(float(top["confidence"]), 4)
        if "angle_deg" in top:
            self._reg.last_angle_deg = round(float(top["angle_deg"]), 2)
            self._reg.last_angle_valid = bool(top.get("angle_valid", False))
        else:
            self._reg.last_angle_deg = 0.0
            self._reg.last_angle_valid = False

    def _publish_state(self, elapsed_s: float) -> None:
        """Опубликовать метрики инференса в StateStore.

        elapsed_s — длительность окна с прошлой публикации (для inference_fps =
        число инференсов / окно; учитывает inference_every_n и простой).
        """
        avg = self._latency_sum_ms / self._latency_count if self._latency_count else 0.0
        fps = self._latency_count / elapsed_s if elapsed_s > 0 else 0.0
        self._reg.avg_latency_ms = round(avg, 2)
        self._reg.last_latency_ms = round(self._last_latency_ms, 2)
        self._reg.max_latency_ms = round(self._max_latency_ms, 2)
        self._reg.inference_fps = round(fps, 1)
        if self._state_proxy is not None:
            path = f"processes.{self._ctx.process_name}.state"
            self._state_proxy.merge(
                path,
                {
                    "status": "running",
                    "loaded_model": self._reg.loaded_model,
                    "active_providers": self._reg.active_providers,
                    "last_label": self._reg.last_label,
                    "last_confidence": self._reg.last_confidence,
                    "last_angle_deg": self._reg.last_angle_deg,
                    "last_angle_valid": self._reg.last_angle_valid,
                    "avg_latency_ms": self._reg.avg_latency_ms,
                    "last_latency_ms": self._reg.last_latency_ms,
                    "max_latency_ms": self._reg.max_latency_ms,
                    "inference_fps": self._reg.inference_fps,
                },
            )
        # avg/max/fps — оконные: сбрасываем. last_latency_ms — НЕ сбрасываем
        # (последнее измеренное значение должно держаться между публикациями).
        self._latency_sum_ms = 0.0
        self._latency_count = 0
        self._max_latency_ms = 0.0
