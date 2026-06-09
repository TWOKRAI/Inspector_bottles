# ml_inference — инференс нейросетей

Сервис инференса для pipeline: на вход BGR-кадр, на выходе классы + confidence.
Старт — классификация (MobileNetV3), архитектура универсальная (задел под детекцию).

## Идея: data-driven + pluggable

- **Model registry + sidecar** — рядом с весами лежит `<basename>.yaml` с описанием
  препроцессинга (input_size, layout, цветопорядок, normalize, labels, backend).
  Добавить модель = положить веса + sidecar в `data/models/`, код не трогаем.
- **Backend-абстракция** (`BaseInferenceBackend`) — ONNX Runtime (основной) и torch
  (опц.) за единым интерфейсом. Задел под TensorRT/OpenVINO.

## Структура

```
core/      — препроцессинг/постобработка + ModelRegistry (без ML-либ: numpy+opencv)
backends/  — ONNXRuntimeBackend (осн.), TorchBackend (TorchScript, опц.)
engine.py  — InferenceEngine: каталог + backend + pre/post, кэш модели, warmup
plugin/    — MLInferencePlugin (тонкий): кадр → engine → predictions (+ overlay)
```

## Установка зависимостей

```bash
pip install '.[ml]'        # onnxruntime + onnx (основной backend)
pip install '.[ml-torch]'  # torch + torchvision (опц., только TorchScript)
```

Graceful degradation: сервис импортируется без ML-библиотек; инференс отключается
с понятной ошибкой, если backend-библиотека не установлена.

## Использование в pipeline

Нода `ml_inference` (category=processing). Инспектор:
- **Модель** — динамический выпадающий список из `data/models` (custom widget `model_picker`);
- **Устройство** — cpu | cuda;
- **Порог уверенности**, **Top-K**, **Инференс каждый N-й кадр**, **Рисовать результат**.

Выходные порты: `frame` (кадр, опц. overlay) + `predictions` (`list[dict]`:
`class_id`, `label`, `confidence`).

Команды (live): `set_model`, `set_threshold`, `reload_model`.

## Формат моделей

См. [`data/models/README.md`](../../data/models/README.md).

## Тесты

```bash
pytest Services/ml_inference/tests/        # core/engine/plugin (dummy ONNX, без реальных весов)
pytest multiprocess_prototype/frontend/forms/tests/test_model_picker.py  # widget
```
