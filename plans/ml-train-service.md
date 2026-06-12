# ml-train-service — универсальный сервис обучения нейросетей

**Ветка:** `feat/ml-train-service`
**Статус:** in progress
**Дата:** 2026-06-13

## Цель

`Services/ml_train` — универсальный сервис обучения и выбора моделей классификации
(+ опциональная регрессия угла) на современном стеке 2026:

- **Модели:** MobileNetV3 Large/Small (torchvision), MobileNetV4 (timm),
  любая архитектура timm по имени `timm/<arch>` — расширяемый реестр.
- **Данные (3 источника):** синтетика `dataset_gen` на лету (SyntheticDataset),
  экспортированный датасет (`labels.csv` + `images/`), папки-классы
  (Good/Bad/Neutral — формат старого keras-кода).
- **Техники:** AMP (bf16/fp16), torch.compile (opt-in), EMA весов, warmup+cosine,
  label smoothing, mixup, class weights (auto-balance), early stopping,
  channels_last, чекпоинт лучшей модели по монитор-метрике.
- **Выбор моделей:** реестр прогонов `runs/<name>/` (config, history, metrics,
  best.pt) + сравнение и выбор лучшего прогона по метрике.
- **Экспорт:** ONNX + sidecar YAML + labels.txt в формате `ml_inference`
  (`data/models/`) — обученная модель сразу подхватывается в pipeline GUI.

## Контракты стыковки

- Вход: `Services/dataset_gen` — `SyntheticDataset` target-словарь
  (`class_index`, `angle` sin/cos, `angle_valid` — маска loss) и формат
  `export_dataset` (`images/{class:03d}/`, `labels.csv`, `classes.json`).
- Выход: sidecar-конвенция `data/models/README.md` (name/task/backend/weights/
  input_size/layout/color/normalize/labels) — `ModelRegistry` из `ml_inference`.

## Задачи

- [x] План + ветка
- [ ] T1. Каркас сервиса: `config.py` (Pydantic, from_yaml/from_dict/to_dict), `interfaces.py`
- [ ] T2. `models.py` — реестр архитектур (torchvision MobileNetV3, timm MobileNetV4, `timm/*` passthrough), мультиголова класс+угол
- [ ] T3. `data.py` — три источника + аугментации + class weights + DataLoader'ы
- [ ] T4. `metrics.py` — numpy-метрики (accuracy, balanced accuracy, confusion matrix, per-class report, angle MAE°)
- [ ] T5. `trainer.py` — цикл обучения (AMP, EMA, mixup, warmup+cosine, early stopping, чекпоинты, history)
- [ ] T6. `selection.py` — RunRegistry: сравнение прогонов, выбор лучшего
- [ ] T7. `export.py` — ONNX + sidecar + labels для `ml_inference` (+ parity-проверка через onnxruntime)
- [ ] T8. `__main__.py` CLI: `train` / `runs` / `export`
- [ ] T9. Пресет `presets/ru_letters_synthetic.yaml` (синтетика dataset_gen)
- [ ] T10. Тесты: config/selection/metrics (без torch) + data/trainer/export (torch, smoke CPU)
- [ ] T11. Документация: README.md, STATUS.md, строка в `Services/STATUS.md`, extra `ml-train` в pyproject

## Out of scope

- Детекция/сегментация (задел в конфиге задачей `task`, реализация — классификация+угол)
- Распределённое обучение (DDP), гиперпараметрический поиск
- GUI-вкладка обучения (отдельный план)
- Квантование INT8/QAT (ONNX dynamic quantization — кандидат на след. итерацию)
