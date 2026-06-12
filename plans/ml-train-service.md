# ml-train-service — универсальный сервис обучения нейросетей

**Ветка:** `feat/ml-train-service`
**Статус:** done (v1)
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
- [x] T1. Каркас сервиса: `config.py` (Pydantic, from_yaml/from_dict/to_dict), `interfaces.py`
- [x] T2. `models.py` — реестр архитектур (torchvision MobileNetV3, timm MobileNetV4, `timm/*` passthrough), мультиголова класс+угол
- [x] T3. `data.py` — три источника + аугментации + class weights + DataLoader'ы
- [x] T4. `metrics.py` — numpy-метрики (accuracy, balanced accuracy, confusion matrix, per-class report, angle MAE°)
- [x] T5. `trainer.py` — цикл обучения (AMP, EMA, mixup, warmup+cosine, early stopping, чекпоинты, history)
- [x] T6. `selection.py` — RunRegistry: сравнение прогонов, выбор лучшего
- [x] T7. `export.py` — ONNX + sidecar + labels для `ml_inference` (+ parity-проверка через onnxruntime)
- [x] T8. `__main__.py` CLI: `train` / `runs` / `export` / `archs`
- [x] T9. Пресет `presets/ru_letters_synthetic.yaml` (синтетика dataset_gen)
- [x] T10. Тесты: 34 (21 без torch + 13 torch smoke CPU, вкл. интеграцию с ModelRegistry ml_inference)
- [x] T11. Документация: README.md, STATUS.md, строка в `Services/STATUS.md`, extra `ml-train` в pyproject

**Верификация:** 39/39 тестов; живой probe синтетики (33 класса, батч 8×3×128×128);
parity torch↔onnxruntime в экспорте; ruff clean.

**Ревью (Fable, 2026-06-13):** APPROVE с замечаниями. MAJOR-1 (resize stretch↔letterbox
при неквадратном входе) — задокументирован в README ml_train + data/models, follow-up:
поле resize-политики в sidecar. MINOR 2-8 и NIT 9-11 исправлены (fallback монитора
angle→val_loss, запрет fp16 на CPU, EMA: warmup-decay + одна eval-копия до compile,
проверка рассинхрона сплитов, защита крошечного train-сплита, KeyError в summary,
собственный rng вместо глобального np.random). Тесты +5: stub-синтетика,
дизъюнктность сплита, рассинхрон сплитов, ONNX с угловой головой.

## Out of scope

- Детекция/сегментация (задел в конфиге задачей `task`, реализация — классификация+угол)
- Распределённое обучение (DDP), гиперпараметрический поиск
- GUI-вкладка обучения (отдельный план)
- Квантование INT8/QAT (ONNX dynamic quantization — кандидат на след. итерацию)
