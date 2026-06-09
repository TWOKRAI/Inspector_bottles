# ml_inference — STATUS

**Готовность:** foundation (классификация, ONNX backend) — 2026-06-08

## Что сделано

- `core/` — `ModelSpec` + `ModelRegistry` (скан + sidecar + sandbox-валидация пути),
  `preprocess` (letterbox/resize + цветопорядок + normalize + layout по spec),
  `postprocess` (softmax + top-k + threshold).
- `backends/` — `BaseInferenceBackend` (ABC), `ONNXRuntimeBackend` (CPU/CUDA providers),
  `TorchBackend` (только TorchScript — безопасно, без pickle-RCE).
- `engine.py` — `InferenceEngine`: каталог + backend + pre/post, lazy-load + warmup +
  выгрузка при смене модели.
- `plugin/` — `MLInferencePlugin` (processing, thread_safe=False): кадр → engine →
  predictions, overlay, телеметрия latency/last_label в StateStore. Команды
  set_model/set_threshold/reload_model. Pass-through при пустой модели и ошибках.
- GUI — кастомный widget `model_picker` (динамический dropdown из `data/models`);
  потребовало 3 правки фреймворка (WidgetType, _WIDGET_TO_KIND, register_type).

## Тесты

- `Services/ml_inference/tests/` — 33 passed (registry/preprocess/postprocess/engine/plugin,
  реальный ONNX через dummy-модель, graceful degradation).
- `multiprocess_prototype/frontend/forms/tests/test_model_picker.py` — widget (3 теста).

## Зависимости

`pip install '.[ml]'` (onnxruntime+onnx). torch-backend опц.: `.[ml-torch]`.

## Дальше (вне текущего scope)

- Детекция (YOLO/NMS), сегментация — задел в `ModelSpec.task`.
- TensorRT/OpenVINO backends через ту же абстракцию.
- Батчинг/async worker-pool инференса.
- ADR при стабилизации контракта.
