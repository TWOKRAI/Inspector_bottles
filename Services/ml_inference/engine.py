"""InferenceEngine — фасад: каталог + backend + препроцессинг + постобработка.

Связывает всё воедино и держит загруженную модель в кэше. Один движок на плагин;
смена модели выгружает предыдущую (освобождение памяти/GPU).

Поток predict():
    BGR-кадр → preprocess(spec) → backend.infer → classify_postprocess → list[dict]
"""

from __future__ import annotations

import logging

import numpy as np

from Services.ml_inference.backends.base import BaseInferenceBackend
from Services.ml_inference.backends.onnx_backend import ONNX_AVAILABLE, ONNXRuntimeBackend
from Services.ml_inference.backends.torch_backend import TORCH_AVAILABLE, TorchBackend
from Services.ml_inference.core.model_spec import ModelSpec
from Services.ml_inference.core.postprocess import angle_postprocess, classify_postprocess
from Services.ml_inference.core.preprocess import preprocess
from Services.ml_inference.core.registry import ModelRegistry

logger = logging.getLogger(__name__)


def _make_backend(backend_type: str) -> BaseInferenceBackend:
    """Фабрика backend по типу из ModelSpec (понятная ошибка если библиотека не стоит)."""
    if backend_type == "onnx":
        if not ONNX_AVAILABLE:
            raise RuntimeError("backend 'onnx' недоступен: pip install '.[ml]'")
        return ONNXRuntimeBackend()
    if backend_type == "torch":
        if not TORCH_AVAILABLE:
            raise RuntimeError("backend 'torch' недоступен: pip install '.[ml-torch]'")
        return TorchBackend()
    raise ValueError(f"неизвестный backend: {backend_type}")


class InferenceEngine:
    """Высокоуровневый движок инференса для одной модели за раз."""

    def __init__(self, models_dir: str) -> None:
        self._registry = ModelRegistry(models_dir)
        self._registry.scan()
        self._backend: BaseInferenceBackend | None = None
        self._spec: ModelSpec | None = None
        self._labels: list[str] | None = None
        self._device: str = "cpu"
        #: метки, для которых уже залогирован fallback симметрии (анти-спам в predict)
        self._warned_symmetry: set[str] = set()

    @property
    def registry(self) -> ModelRegistry:
        """Каталог моделей (для GUI-списка)."""
        return self._registry

    @property
    def current_model(self) -> str | None:
        """Имя текущей загруженной модели или None."""
        return self._spec.name if self._spec else None

    @property
    def is_ready(self) -> bool:
        """Готов ли движок к predict()."""
        return self._backend is not None and self._backend.is_loaded

    @property
    def active_providers(self) -> list[str]:
        """Фактические execution-providers/устройство загруженного backend.

        Для ONNX это реальные providers сессии (напр. ['CPUExecutionProvider']
        даже если запрашивали cuda — fallback). Пустой список, если не загружено.
        Нужно телеметрии: оператор должен видеть, что cuda молча уехала на CPU.
        """
        return self._backend.active_providers if self._backend is not None else []

    def load_model(self, model_id: str, device: str = "cpu") -> None:
        """Загрузить модель по id из каталога (с выгрузкой предыдущей)."""
        spec = self._registry.get(model_id)
        if spec is None:
            # перескан на случай новых файлов
            self._registry.scan()
            spec = self._registry.get(model_id)
        if spec is None:
            raise ValueError(f"модель не найдена в каталоге: {model_id}")

        self.unload()
        backend = _make_backend(spec.backend)
        backend.load(spec, device=device)
        backend.warmup()
        self._backend = backend
        self._spec = spec
        self._labels = spec.load_labels()
        self._device = device
        self._warned_symmetry = set()
        self._check_symmetry_coverage(spec)
        logger.info("InferenceEngine: модель '%s' готова (%s)", model_id, device)

    def _check_symmetry_coverage(self, spec: ModelSpec) -> None:
        """Предупредить, если у angle-модели метки не покрыты картой симметрии.

        Метка вне symmetry-карты на инференсе трактуется консервативно как 'full'
        (angle_valid=False, доворот не делается) — см. _symmetry_for. Это fail-safe:
        для реально full-объекта (круг) лучше не доворачивать, чем по мусорному углу.
        Но молчать о пробеле нельзя — он обычно означает опечатку/рассинхрон sidecar.
        """
        if not spec.angle_head or not self._labels:
            return
        missing = [lbl for lbl in self._labels if lbl not in spec.symmetry]
        if missing:
            logger.warning(
                "InferenceEngine: модель '%s' с angle_head, но %d меток вне symmetry-карты "
                "(%s%s) — для них угол трактуется как 'full' (angle_valid=False). "
                "Проверьте sidecar: пробел обычно = опечатка/рассинхрон ключей.",
                spec.name,
                len(missing),
                ", ".join(missing[:8]),
                "…" if len(missing) > 8 else "",
            )

    def _symmetry_for(self, label: str) -> str:
        """Симметрия класса из sidecar; fail-safe 'full' для непокрытой метки.

        Дефолт НЕ 'none': 'none' дал бы angle_valid=True и конкретный угол для
        объекта неизвестной симметрии (круг → доворот наугад). 'full' → valid=False.
        """
        if self._spec is None:
            return "full"
        sym = self._spec.symmetry.get(label)
        if sym is None:
            if label not in self._warned_symmetry:
                self._warned_symmetry.add(label)
                logger.warning(
                    "predict: класс '%s' отсутствует в symmetry-карте — угол как 'full' "
                    "(angle_valid=False, без доворота)",
                    label,
                )
            return "full"
        return sym

    def predict(self, frame: np.ndarray, *, top_k: int = 5, threshold: float = 0.0) -> list[dict]:
        """BGR-кадр → топ-K предсказаний (+ угол у top-1, если angle_head).

        Пустой список если движок не готов. У top-1 добавляются angle_deg/
        angle_valid с учётом симметрии распознанного класса (full → valid=False).
        """
        if not self.is_ready or self._spec is None or self._backend is None:
            return []
        tensor = preprocess(frame, self._spec)
        outputs = self._backend.infer(tensor)
        logits = outputs.get(self._spec.output_name)
        if logits is None:  # одноголовая модель / иное имя — берём первый выход
            logger.warning(
                "predict: выход '%s' не найден в %s — fallback на первый выход (проверьте sidecar output_name)",
                self._spec.output_name,
                list(outputs),
            )
            logits = next(iter(outputs.values()))
        preds = classify_postprocess(logits, labels=self._labels, top_k=top_k, threshold=threshold)

        if self._spec.angle_head and preds:
            angle_raw = outputs.get(self._spec.angle_output_name)
            if angle_raw is not None:
                sym = self._symmetry_for(preds[0]["label"])
                preds[0].update(angle_postprocess(angle_raw, sym))
        return preds

    def unload(self) -> None:
        """Выгрузить текущую модель и освободить ресурсы."""
        if self._backend is not None:
            self._backend.unload()
        self._backend = None
        self._spec = None
        self._labels = None
