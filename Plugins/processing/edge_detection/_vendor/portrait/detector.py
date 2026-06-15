"""U2Net Portrait edge detector — ONNX inference (порт из sketch_robot)."""

from __future__ import annotations

import cv2
import numpy as np


class U2NetPortraitDetector:
    """U²-Net Portrait Drawing — художественные контурные линии через ONNX.

    Standalone: принимает путь к весам, отдаёт нормализованную карту [0..1]
    (порог/инверсию делает вызывающий плагин). Размер входа берётся из модели
    (обычно 512×512), нормализация RGB [0,1] NCHW.
    """

    def __init__(self, weights_path: str, providers: list[str] | None = None) -> None:
        import onnxruntime as ort

        avail = ort.get_available_providers()
        prov = providers or [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in avail]
        self._session = ort.InferenceSession(weights_path, providers=prov)
        info = self._session.get_inputs()[0]
        self._name = info.name
        mh, mw = info.shape[2], info.shape[3]
        self._h = mh if isinstance(mh, int) else 512
        self._w = mw if isinstance(mw, int) else 512

    def infer_map(self, image: np.ndarray) -> np.ndarray:
        """BGR-кадр → нормализованная карта [0..1] float32 в РАЗМЕРЕ исходного кадра."""
        h, w = image.shape[:2]
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (self._w, self._h))
        inp = (resized.astype(np.float32) / 255.0).transpose(2, 0, 1)[np.newaxis, ...]
        out = self._session.run(None, {self._name: inp})[0].squeeze()
        out = (out - out.min()) / (out.max() - out.min() + 1e-8)
        if out.shape[0] != h or out.shape[1] != w:
            out = cv2.resize(out, (w, h), interpolation=cv2.INTER_LINEAR)
        return out.astype(np.float32)
