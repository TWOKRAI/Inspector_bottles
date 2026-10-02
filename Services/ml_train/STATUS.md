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
- `service.py` — фасад IService для вкладки «Сервисы» (реестр прогонов + готовность
  ML-стека; torch НЕ импортируется при discovery)
- Тесты: 39 + 3 фасадных (config/metrics/selection без torch; data/trainer/export — torch smoke CPU)

## eval: вырез по формуле конвейера (Task 6.4)

- `holdout_eval._crop_disk` режет кадр как `center_crop`: `side_from_radius` + `square_crop(oob="pad")` + `resize_square`;
  `evaluate_holdout(radius_scale, margin_px, output_size, pad_color_bgr)` вместо `margin` (внешних вызовов с `margin` — 0);
  сводка содержит `"crop"`. CLI `eval`: `--radius-scale`, `--margin-px`, `--output-size`, `--pad-color-bgr B,G,R`.
- Исправлен `IndexError` в строке лога на промахе буквы (`err=` только при `ok and angle_valid`).
- Прогон лида 2026-10-02 (модель `mobilenet_v3_large_20260616_050828`, `data/real_photos`: 8 кадров, 2 буквы, участвовали
  в обучении; CPU, ONNX):

  | Формула | Точность буквы | MAE угла | p95 угла | Доля ≤5° | Кадров с углом |
  |---|---|---|---|---|---|
  | старая (`b8e57092` + локальная правка `ok and` — без неё `IndexError`) | 0.500 (А 0/4, С 4/4) | 8.59° | 12.24° | 0.25 | 4 |
  | новая (`1d618b0b`) | 0.625 (А 1/4, С 4/4) | 37.74° | 104.48° | 0.00 | 5 |

  Контрольные варианты выреза (подмена в процессе, вне git; скрипт ревьюера, повторён лидом — числа совпали):

  | Вариант | Точность | MAE угла | Доля ≤5° | Кадров с углом |
  |---|---|---|---|---|
  | новая сторона + `replicate` + resize 128 | 0.500 | 6.78° | 0.25 | 4 |
  | старая сторона + чёрная заливка, без resize | 0.500 | 20.42° | 0.00 | 4 |
  | новая сторона + чёрная заливка, без resize | 0.625 | 42.17° | 0.00 | 5 |
  | новая сторона + заливка медианой рамки кадра + resize 128 | 0.500 | 21.18° | 0.00 | 4 |
  | `margin_px 0` (сторона 2r, вырез внутри кадра, без заливки) + resize 128 | 0.500 | 17.82° | 0.00 | 4 |
  | сырой кадр без выреза | 0.500 | 16.32° | 0.00 | 4 |

  **Число не меряет вид робота.** Кадры `real_photos` — уже вырезанные 124×124 с диском r≈58–61 (замер `detect_disk`).
  Сторона выреза больше кадра в обеих формулах (старая 136–144 px, новая 144–150 px), поэтому вырез выходит за край на
  каждом кадре. Что показывают контроли:
  - число держит вид заливки: хорошие 7–9° даёт только `replicate`; любая постоянная заливка (чёрная, медиана рамки) — 20–42°;
  - при постоянной заливке влияет и сторона: она задаёт ширину заливки (чёрная: 20.4° на старой стороне, 42.2° на новой);
  - варианты без заливки вовсе дают 16–18°, не 7–9°: хорошее старое число — свойство `replicate` на уже вырезанных кадрах,
    а не ожидание для полного кадра камеры.

  N=8, кадров с углом 4–5, один прогон без повторов: это наблюдение, не замер (кадр C_000 даёт от 1° до 123° по варианту).
  Честное число — после сбора отложенной выборки со стенда полными кадрами (→ letters-retrain).

## Ревью

Fable-ревью 2026-06-13: APPROVE с замечаниями; MAJOR-1 (resize-политика)
задокументирован, MINOR 2-8 и NIT 9-11 исправлены, добавлены тесты
(stub-синтетика, дизъюнктность сплита, ONNX с угловой головой).

## Известные ограничения

- **Resize-политика train↔inference:** обучение — stretch, ml_inference —
  letterbox (дефолт `keep_aspect=True`). Для квадратного входа эквивалентно;
  для неквадратного ROI — подавать квадратные кропы (см. README). Follow-up:
  поле resize-политики в sidecar + поддержка в ml_inference.preprocess
- Интерполяция: `v2.Resize(antialias=True)` при обучении vs `cv2.INTER_LINEAR`
  при инференсе — мелкий численный дрейф при сильном downscale (допущение)

- ONNX-экспорт через legacy TorchScript-путь (`dynamo=False`) — стабильный
  выбор для tuple-выхода `(logits, angle|None)`; миграция на dynamo-экспорт
  по мере зрелости
- Без resume после прерывания (last.pt сохраняется, перезапуск — с нуля)
- Без DDP, без гиперпараметрического поиска, без INT8/QAT-квантования
- `angle_mae_deg` в history/metrics.json — ФИЗИЧЕСКИЙ MAE (с учётом factor=2 для
  symmetry=180; делить на 2 НЕ нужно): для synthetic/exported `class_symmetry`
  всегда задан → `evaluation_summary` идёт по `angle_report`. Кодированный MAE
  (вдвое больше) возникает лишь в редком fallback без symmetry-карты

## Следующие шаги (по потребности)

- ONNX dynamic quantization (INT8) при экспорте — ускорение CPU-инференса
- GUI-вкладка обучения (запуск/мониторинг прогонов из прототипа)
- resume-обучение из last.pt
