"""EdgeDetectionPlugin — детекция линий портрета нейросетью TEED (line-art).

Порт логики из projects_obsidian/sketch_robot/modules/edge_detection.py (класс
TEEDDetector). Вход — BGR-кадр, выход — бинарная карта линий. Два порта:
- frame: BGR-рендер линий (белым по чёрному) — для дисплея;
- mask:  бинарная маска uint8 0/255 — для downstream (blob_filter, strokes_to_points).

TEED (~58K параметров, PyTorch) лениво грузится при первом кадре. Веса —
из ~/.cache/sketch_robot/ или data/models/teed/ (см. _vendor/teed/resolve_weights).
torch — из extras [ml]. Без CUDA — авто-fallback на cpu.
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from multiprocess_framework.modules.process_module.plugins import (
    PluginContext,
    Port,
    ProcessModulePlugin,
    for_each,
    register_plugin,
)

from .registers import EdgeDetectionRegisters

# BGR mean из VGG-предобработки TEED (так обучалась сеть): BGR, [0,255], minus mean.
_BGR_MEAN = np.array([103.939, 116.779, 123.68], dtype=np.float32)


@register_plugin(
    "edge_detection",
    category="processing",
    description="Детекция линий портрета нейросетью TEED (line-art)",
)
class EdgeDetectionPlugin(ProcessModulePlugin):
    """BGR-кадр → TEED → frame(BGR line-art) + mask(бинарь 0/255)."""

    name = "edge_detection"
    category = "processing"
    thread_safe = False  # ленивая модель + кэш кадров между вызовами

    inputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="Входной BGR-кадр"),
    ]
    outputs = [
        Port(name="frame", dtype="image/bgr", shape="(H, W, 3)", description="BGR-рендер линий (line-art)"),
        Port(name="mask", dtype="image/gray", shape="(H, W)", description="Бинарная маска линий 0/255"),
    ]

    commands: dict[str, str] = {}
    register_class = EdgeDetectionRegisters

    @classmethod
    def config_class(cls) -> type | None:
        from .config import EdgeDetectionPluginConfig

        return EdgeDetectionPluginConfig

    # ------------------------------------------------------------------ #
    # LIFECYCLE
    # ------------------------------------------------------------------ #

    def configure(self, ctx: PluginContext) -> None:
        self._ctx = ctx
        self._reg: EdgeDetectionRegisters = self._init_register(ctx)
        self._model: Any = None
        self._device: Any = None
        self._torch: Any = None
        self._u2net: Any = None  # U2Net Portrait (ONNX) — лениво
        self._frame_idx = 0
        self._last_mask: np.ndarray | None = None
        self._load_failed = False
        ctx.log_info(
            f"EdgeDetectionPlugin: method={self._reg.method} threshold={self._reg.threshold} device={self._reg.device}"
        )

    def shutdown(self, ctx: PluginContext) -> None:
        # Освобождаем модель (GPU-память для cuda).
        self._model = None
        self._last_mask = None
        ctx.log_info("EdgeDetectionPlugin: shutdown")

    # ------------------------------------------------------------------ #
    # МОДЕЛЬ
    # ------------------------------------------------------------------ #

    def _infer(self, frame: np.ndarray) -> np.ndarray:
        """Диспетчер метода: TEED или U2Net Portrait → бинарная карта (uint8 0/255)."""
        method = str(self._reg.method).strip().lower()
        if method in ("u2net_portrait", "u2net", "portrait"):
            return self._infer_u2net(frame)
        return self._infer_teed(frame)

    def _load_teed(self) -> None:
        try:
            import torch
        except ImportError as exc:  # pragma: no cover - окружение без torch
            raise ImportError("Для TEED нужен PyTorch. Установите extras: uv pip install '.[ml]'") from exc

        from ._vendor.teed import TED, resolve_weights

        want = str(self._reg.device).strip().lower()
        use_cuda = want == "cuda" and torch.cuda.is_available()
        device = torch.device("cuda" if use_cuda else "cpu")
        weights = resolve_weights(self._reg.weights_path or None)

        model = TED()
        # Безопасность: сначала пробуем weights_only=True (только тензоры). Старый
        # чекпоинт TEED сохранён в pickle-формате — при неудаче падаем на False
        # (файл локальный и доверенный, кладётся владельцем вручную).
        try:
            state = torch.load(weights, map_location=device, weights_only=True)
        except Exception:
            self._ctx.log_info(
                "EdgeDetectionPlugin: weights_only=True не сработал (старый формат), "
                "загрузка с weights_only=False (доверенный локальный файл)"
            )
            state = torch.load(weights, map_location=device, weights_only=False)  # nosec B614 — доверенный локальный чекпоинт TEED
        model.load_state_dict(state)
        model.to(device)
        model.eval()

        self._torch = torch
        self._model = model
        self._device = device
        self._ctx.log_info(f"EdgeDetectionPlugin: TEED загружен (device={device}, weights={weights})")

    def _infer_teed(self, frame: np.ndarray) -> np.ndarray:
        """BGR-кадр → бинарная карта линий (uint8 0/255), размер исходного кадра."""
        if self._model is None:
            self._load_teed()
        torch = self._torch

        img = frame.astype(np.float32)
        h, w = img.shape[:2]

        # TEED требует размеры кратные 16.
        new_h = (h // 16) * 16
        new_w = (w // 16) * 16
        if new_h != h or new_w != w:
            img = cv2.resize(img, (new_w, new_h))

        img = img - _BGR_MEAN
        tensor = torch.from_numpy(img).permute(2, 0, 1).unsqueeze(0).to(self._device)

        with torch.no_grad():
            preds = self._model(tensor)

        # Последний выход (fused) — наиболее точный.
        edge_map = torch.sigmoid(preds[-1]).squeeze().cpu().numpy()
        binary = (edge_map > float(self._reg.threshold)).astype(np.uint8) * 255

        if binary.shape[0] != h or binary.shape[1] != w:
            binary = cv2.resize(binary, (w, h), interpolation=cv2.INTER_NEAREST)
        return binary

    def _infer_u2net(self, frame: np.ndarray) -> np.ndarray:
        """BGR-кадр → художественный портрет U2Net (uint8 0/255)."""
        if self._u2net is None:
            from ._vendor.portrait import U2NetPortraitDetector, resolve_portrait_weights

            weights = resolve_portrait_weights(self._reg.weights_path or None)
            self._u2net = U2NetPortraitDetector(weights)
            self._ctx.log_info(f"EdgeDetectionPlugin: U2Net Portrait загружен (weights={weights})")

        pred = self._u2net.infer_map(frame)  # [0..1], размер кадра
        binary = (pred > float(self._reg.threshold)).astype(np.uint8) * 255
        return binary

    # ------------------------------------------------------------------ #
    # PROCESS
    # ------------------------------------------------------------------ #

    @for_each
    def process(self, item: dict) -> dict | None:
        frame = item.get("frame")
        if frame is None:
            return None

        every = max(1, int(self._reg.inference_every_n))
        self._frame_idx += 1
        run_now = self._last_mask is None or (self._frame_idx % every == 0)

        if run_now and not self._load_failed:
            try:
                self._last_mask = self._infer(frame)
            except FileNotFoundError as exc:
                # Веса не найдены — деградация: логируем один раз, пропускаем кадр.
                self._load_failed = True
                self._ctx.log_error(f"EdgeDetectionPlugin: {exc}")
                return item
            except Exception as exc:  # pragma: no cover - защита горячего пути
                self._ctx.log_error(f"EdgeDetectionPlugin: инференс упал: {exc}")
                return item

        mask = self._last_mask
        if mask is None:
            return item

        if self._reg.invert:
            mask = 255 - mask

        line_bgr = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)
        return {**item, "frame": line_bgr, "mask": mask}
