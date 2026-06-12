# ml_train — STATUS

**Готовность:** ready (v1)
**Обновлено:** 2026-06-13

## Что сделано

- `TrainConfig` (Pydantic, YAML/dict) — полный конфиг прогона, кросс-валидация
  (mixup×angle_head, monitor×angle_head)
- Реестр архитектур: MobileNetV3 L/S (torchvision), MobileNetV4 (timm),
  `timm/<имя>` passthrough; мультиголовая модель (классы + угол sin/cos)
- 3 источника данных: synthetic (dataset_gen на лету), exported
  (labels.csv/json + images/), folder (подпапки-классы); balanced class weights
- Trainer: AdamW, warmup+cosine/plateau, AMP (bf16/fp16 auto), EMA, mixup,
  label smoothing, channels_last, torch.compile (opt-in), early stopping,
  crash-safe history, авто-оценка на test-сплите
- Метрики на numpy (без sklearn): accuracy, balanced accuracy, per-class
  precision/recall/f1, confusion matrix, angle MAE° (masked, с wrap-around)
- `RunRegistry` — сравнение прогонов и выбор лучшего (работает без torch)
- `export_onnx`: ONNX (динамический batch) + sidecar + classes.txt в формате
  `ml_inference`; parity-проверка torch↔ORT; интеграционный тест с `ModelRegistry`
- CLI: `train` / `runs` / `export` / `archs`; пресет `ru_letters_synthetic.yaml`
- Тесты: 34 (21 без torch + 13 с torch, smoke-обучение на CPU)

## Известные ограничения

- ONNX-экспорт через legacy TorchScript-путь (`dynamo=False`) — стабильный
  выбор для tuple-выхода `(logits, angle|None)`; миграция на dynamo-экспорт
  по мере зрелости
- Без resume после прерывания (last.pt сохраняется, перезапуск — с нуля)
- Без DDP, без гиперпараметрического поиска, без INT8/QAT-квантования
- `angle_mae_deg` — в кодированном пространстве угла (для symmetry=180
  физическая ошибка вдвое меньше показанной)

## Следующие шаги (по потребности)

- ONNX dynamic quantization (INT8) при экспорте — ускорение CPU-инференса
- GUI-вкладка обучения (запуск/мониторинг прогонов из прототипа)
- resume-обучение из last.pt
