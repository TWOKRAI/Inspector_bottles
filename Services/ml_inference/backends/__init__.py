"""backends — реализации backend-рантаймов инференса.

BaseInferenceBackend импортируется всегда (чистый ABC). Конкретные backend
(ONNX/torch) подтягиваются лениво и сообщают о доступности через флаги *_AVAILABLE.
"""

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.backends.onnx_backend import ONNX_AVAILABLE, ONNXRuntimeBackend
from Services.ml_inference.backends.torch_backend import TORCH_AVAILABLE, TorchBackend

__all__ = [
    "BaseInferenceBackend",
    "ONNXRuntimeBackend",
    "ONNX_AVAILABLE",
    "TorchBackend",
    "TORCH_AVAILABLE",
]
