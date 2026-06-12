# ml_train — универсальный сервис обучения и выбора моделей

## Назначение

Обучение классификаторов (+ опциональная регрессия угла поворота) на стеке
PyTorch 2.x и выбор лучшей модели по метрикам. Замыкает конвейер:
**dataset_gen** (данные) → **ml_train** (обучение) → **ml_inference** (инференс
в pipeline GUI): экспортированная модель сразу видна `ModelRegistry`.

Один YAML-конфиг = воспроизводимый эксперимент: архитектура, данные,
оптимизация, режим, экспорт.

## Публичный API

| Символ | Описание |
|--------|----------|
| `TrainConfig` | Pydantic-конфиг прогона; `from_yaml` / `from_dict` / `to_dict` |
| `Trainer`, `train` | цикл обучения (AMP, EMA, mixup, warmup+cosine, early stopping) |
| `RunRegistry`, `RunInfo` | каталог прогонов: сравнение, `best(metric)` — без torch |
| `build_model`, `available_archs` | реестр архитектур, мультиголовая модель |
| `build_dataloaders` | данные по конфигу (3 источника) |
| `ExportedDataset`, `FolderDataset` | datasets для готовых файлов |
| `export_onnx`, `load_checkpoint` | экспорт в ONNX + sidecar для ml_inference |
| `PRESETS_DIR` | комплектные пресеты конфигов |

torch-зависимые символы импортируются лениво — конфиги и реестр прогонов
работают в окружении без ML-стека (GUI-процесс, CI).

## Установка

```bash
pip install '.[ml-train]'   # torch + torchvision + timm + onnx
```

GPU-сборку torch (CUDA) ставьте по инструкции pytorch.org под свой драйвер —
extra фиксирует только минимальные версии.

## Архитектуры

| Имя | Источник |
|-----|----------|
| `mobilenet_v3_large`, `mobilenet_v3_small` | torchvision (pretrained ImageNet) |
| `mobilenetv4_small/medium/large`, `mobilenetv4_hybrid_medium/large` | timm |
| `timm/<имя>` | **любая** архитектура timm (сотни моделей) без правок кода |

Модель всегда мультиголовая: backbone → голова классов (+ голова угла
`(sin, cos)` при `model.angle_head: true`). Декодирование угла — `atan2(sin, cos)`
(нормировка выхода не требуется); loss по углу маскируется `angle_valid`
(классы с полной симметрией исключаются — контракт dataset_gen).

## Источники данных (`data.source`)

| Источник | Что это |
|----------|---------|
| `synthetic` | генерация на лету через `Services.dataset_gen` (`generator_preset` — YAML движка); train/val — независимые сиды |
| `exported` | датасет `export_dataset`/`export_splits` (`root` с `train/val[/test]` либо один набор + `val_split`) |
| `folder` | подпапки-классы с картинками (Good/Bad/Neutral — формат старых съёмок), вложенность допустима |

Единый контракт сэмпла: `(image CHW float32 normalized, {class_index, angle,
angle_valid})`. Веса классов `auto` — балансировка `total / (C · count)`.

## Техники обучения (всё конфигом)

AdamW + линейный warmup → cosine (или plateau) · label smoothing · AMP
(bf16/fp16, `auto`) · EMA весов (`ema_decay`) · mixup (`mixup_alpha`, только без
угловой головы) · `torch.compile` (opt-in) · channels_last · early stopping ·
чекпоинт лучшей эпохи по `train.monitor` (balanced_accuracy по умолчанию).

## Быстрый старт

```bash
# обучить 33 русские буквы на синтетике dataset_gen (+ авто-экспорт в ONNX):
python -m Services.ml_train train Services/ml_train/presets/ru_letters_synthetic.yaml

# таблица прогонов и лучший чекпоинт:
python -m Services.ml_train runs

# экспорт вручную (модель появится в выпадающем списке Pipeline GUI):
python -m Services.ml_train export data/ml_train/runs/<run>/best.pt --model-id my_model
```

Программно:

```python
from Services.ml_train import TrainConfig, train, RunRegistry, export_onnx

result = train(TrainConfig.from_yaml("my_config.yaml"))

reg = RunRegistry("data/ml_train/runs")
reg.scan()
best = reg.best("balanced_accuracy")
export_onnx(best.checkpoint, model_id="prod_classifier")
```

## Артефакты прогона (`runs_dir/<run>/`)

`config.yaml` (снимок конфига) · `classes.txt` · `history.json` (по эпохам,
crash-safe) · `metrics.json` (лучшая эпоха + per-class отчёт + confusion matrix,
test-метрики при наличии test-сплита) · `best.pt` / `last.pt` (самодостаточные
чекпоинты: веса + конфиг + классы + размер входа).

## Экспорт в ml_inference

`export_onnx` пишет в `data/models/`: `<id>.onnx` (динамический batch) +
`<id>.yaml` sidecar (препроцессинг по конвенции `data/models/README.md`) +
`<id>_classes.txt`. Parity-проверка torch↔onnxruntime (max|Δ| ≤ 1e-3) — при
установленном onnxruntime. При угловой голове у ONNX два выхода
(`logits`, `angle`); ml_inference использует первый.

## Границы

- НЕ генерирует данные (это `dataset_gen`) и НЕ инференсит в pipeline (это `ml_inference`)
- Детекция/сегментация — задел (`task` в sidecar), реализована классификация (+угол)
- Без DDP/мульти-GPU и гиперпараметрического поиска (по потребности)
- Чистая библиотека уровня Services: без GUI/IPC, не импортирует `multiprocess_prototype.*`

## Тесты

```bash
pytest Services/ml_train/tests/   # config/metrics/selection — без torch;
                                  # data/trainer/export — пропускаются без ML-стека
```
