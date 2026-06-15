---
name: project-letter-angle-training
description: Обучение «буква+угол» на дисках для робота-укладчика; пресеты manual_letters
metadata:
  type: project
---

Задача: на конвейере диск с буквой под случайным углом → распознать **букву + угол поворота**, робот хватает и кладёт на стол с доворотом до 0°. Цель — 33 русские буквы.

Конвейер (synthetic on-the-fly, файлы на диск НЕ пишутся): эталоны выровнены в 0° (`data/dataset_gen/manual_sprites/<буква>/*.png`, по ~8 реальных вырезов: 4 угла × 2 света; погрешность выравнивания 1–2°) → dataset_gen поворачивает на 0–360° (угол = GT-метка) + вклейка на реальную ленту + фотометрия → ml_train (mobilenet_v3_large + angle_head) → ONNX → ml_inference.

Созданные пресеты:
- `Services/dataset_gen/presets/manual_letters_disk.yaml` — генератор: фон `data/backgrounds/belt/` (16 тайлов, нарезаны из 2 чистых кадров ленты), симметрия overrides (О→full; Ж,И,Н,Ф,Х→180), object_size_frac 0.72–0.95 под кроп диска.
- `Services/ml_train/presets/manual_letters.yaml` — боевой (large, angle_head, 60 эпох, batch 32 под RTX 3050).
- `Services/ml_train/presets/manual_letters_smoke.yaml` — быстрый смоук (small, 10 эпох).

Статус 2026-06-15: 12 из 33 букв. Смоук (small,CPU,10эп): bal_acc 0.95, angle_mae 23°. Классификация решается мгновенно (large+pretrained → 96% за 1 эпоху); **узкое место и фокус — точность угла** (для робота нужны единицы градусов). Рычаги: large+60эп+EMA, точность выравнивания эталонов в 0° (потолок), angle_loss_weight↑, monitor=angle_mae_deg при насыщении классификации, больше эталонов/класс. Фон рандомизирован → декоррелирован от класса/угла, сеть вынуждена читать глиф. См. [[project-cuda-torch-setup]], [[project-ml-train-service]], [[project-dataset-gen-service]].
