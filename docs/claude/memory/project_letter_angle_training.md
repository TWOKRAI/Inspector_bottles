---
name: project-letter-angle-training
description: Обучение «буква+угол» на дисках для робота-укладчика; пресеты manual_letters
metadata:
  type: project
---

Задача: на конвейере диск с буквой под случайным углом → распознать **букву + угол поворота**, робот хватает и кладёт на стол с доворотом до 0°. Цель — 33 русские буквы.

Конвейер (synthetic on-the-fly, файлы на диск НЕ пишутся): эталоны выровнены в один 0° (`data/dataset_gen/manual_sprites/<буква>/*.png`, RGBA 128×128, по 4 реальных выреза на класс — ВСЕ под одним углом, не 4×90°) → dataset_gen поворачивает на 0–360° (угол = GT-метка) + вклейка на реальную ленту + фотометрия → ml_train (mobilenet_v3_large + angle_head) → ONNX → ml_inference.

Созданные пресеты:
- `Services/dataset_gen/presets/manual_letters_disk.yaml` — генератор: фон `data/backgrounds/belt/` (12 тайлов, нарезаны из снапшота `main_20260616_043917_555.png`; старые 16 → `data/backgrounds/_belt_old_jun15/`; зелёные рейки сверху y0–19 / снизу y464–483 вырезаны), симметрия overrides (О→full; Ж,И,Н,Ф,Х→180), object_size_frac 0.72–0.95 под кроп диска.
- `Services/ml_train/presets/manual_letters.yaml` — боевой (large, angle_head, 60 эпох, batch 32 под RTX 3050, **monitor=angle_mae_deg, angle_loss_weight 1.5**).
- `Services/ml_train/presets/manual_letters_smoke.yaml` — быстрый смоук (small, 10 эпох).

Статус 2026-06-16: **33/33 буквы обучены до продакшен-цели.** Прогон `mobilenet_v3_large_20260616_050828`: acc/bal_acc **100%**, **angle_mae 1.58°** (P95 4.2°, within-5° 97.3%, none 1.66° / 180° 1.15°, худшая Э 2.31°). ONNX в `data/models/mobilenet_v3_large_20260616_050828.onnx` (+sidecar+classes), parity OK. **Урок (подтверждён на практике):** при насыщении классификации (acc=1.0 на эпохе 6) `monitor=balanced_accuracy` морозит best.pt рано (угол 5.42°) и early-stop рвёт прогон — для угловой задачи ОБЯЗАТЕЛЬНО `monitor=angle_mae_deg` (min). Угол падал 58°→1.58° по косинусу за 60 эпох. ОСТАЛОСЬ: реальный hold-out (`ml_train eval` на фото реальных дисков с известной буквой+углом) — единственная честная проверка переноса; калибровка нуля модель↔робот. Фон рандомизирован → декоррелирован от класса/угла, сеть вынуждена читать глиф. См. [[project-cuda-torch-setup]], [[project-ml-train-service]], [[project-dataset-gen-service]].
