"""TorchBackend — backend на PyTorch/torchvision (.pt / TorchScript).

Опциональный (extra `ml-torch`). Graceful import: без torch модуль импортируется,
но создание backend бросит понятную ошибку.

Безопасность: загружаем ТОЛЬКО TorchScript (`torch.jit.load`) — он не исполняет
произвольный pickle-код. Полный `torch.load(weights_only=False)` НЕ используется
(это RCE через pickle). Для не-TorchScript моделей экспортируйте в ONNX (основной
backend) или в TorchScript: `torch.jit.script(model).save(...)`.

Инференс — в режиме eval() + no_grad.
"""

from __future__ import annotations

import gc
import logging

import numpy as np

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.core.model_spec import ModelSpec

logger = logging.getLogger(__name__)

try:
    import torch

    TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover — зависит от окружения
    torch = None  # type: ignore[assignment]
    TORCH_AVAILABLE = False


class TorchBackend(BaseInferenceBackend):
    """Инференс через PyTorch."""

    def __init__(self) -> None:
        super().__init__()
        if not TORCH_AVAILABLE:
            raise RuntimeError("torch не установлен. Установите: pip install '.[ml-torch]'")
        self._model = None

    def load(self, spec: ModelSpec, device: str = "cpu") -> None:
        """Загрузить TorchScript-модель из .pt.

        Безопасно: jit.load не исполняет произвольный pickle. Если файл не
        TorchScript — понятная ошибка с инструкцией по экспорту (без RCE-пути).
        """
        dev = device if (device == "cuda" and torch.cuda.is_available()) else "cpu"
        if device == "cuda" and dev == "cpu":
            logger.warning("TorchBackend: CUDA недоступна, fallback на CPU")
        path = str(spec.weights_path)
        try:
            # nosec B614 — jit.load загружает TorchScript и НЕ исполняет произвольный
            # pickle (в отличие от torch.load); путь к весам sandbox'ится в ModelRegistry.
            model = torch.jit.load(path, map_location=dev)  # nosec B614
        except (RuntimeError, ValueError) as exc:
            raise RuntimeError(
                f"TorchBackend: '{spec.weights_path.name}' не является TorchScript. "
                "Экспортируйте модель в ONNX (основной backend) или в TorchScript "
                "(torch.jit.script(model).save(...)). Полный torch.load небезопасен и отключён."
            ) from exc
        model.eval()
        self._model = model.to(dev)
        self._spec = spec
        self._device = dev
        logger.info("TorchBackend: загружена %s (%s)", spec.name, dev)

    def infer(self, tensor: np.ndarray) -> dict[str, np.ndarray]:
        """Прогнать тензор → выходы по именам.

        TorchScript не несёт имён выходов → маппим по конвенции spec:
        первый выход = output_name (logits), второй = angle_output_name (angle),
        остальные = out_<i>. Одиночный тензор → только output_name.
        """
        if self._model is None:
            raise RuntimeError("TorchBackend: модель не загружена")
        with torch.no_grad():
            inp = torch.from_numpy(tensor).to(self._device)
            out = self._model(inp)
        # MultiHeadModel.forward отдаёт (logits, None) при angle_head=False —
        # None-выходы отбрасываем, чтобы не звать None.detach()
        outs = list(out) if isinstance(out, (list, tuple)) else [out]
        outs = [t for t in outs if t is not None]
        names = [self._spec.output_name if self._spec else "logits"]
        if self._spec is not None:
            names.append(self._spec.angle_output_name)
        result: dict[str, np.ndarray] = {}
        for i, t in enumerate(outs):
            name = names[i] if i < len(names) else f"out_{i}"
            result[name] = t.detach().cpu().numpy()
        return result

    def unload(self) -> None:
        """Освободить модель + GPU-память."""
        if self._model is not None and self._device == "cuda":
            self._model.cpu()
        self._model = None
        self._spec = None
        gc.collect()
        if TORCH_AVAILABLE and torch.cuda.is_available():
            torch.cuda.empty_cache()
