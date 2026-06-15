---
date: 2026-06-15
topic: Аудит цепочки буква+угол на дисках (аугментация → обучение → инференс)
machine: Windows
branch: main
---

## Session goal

Поднять и проверить полную цепочку распознавания «буква + угол поворота» на дисках конвейера для робота-укладчика (хватает диск, кладёт на стол с доворотом до 0°). За сессию: подготовлены пресеты, обучена модель, замерена латентность, добавлена телеметрия в плагин. **Цель нового чата — провести независимый аудит всей цепочки, убедиться что всё четко, найти замечания.**

## Контекст задачи

- 33 русские буквы на одинаковых белых глянцевых дисках, конвейер, случайный поворот.
- На выходе нужно: **какая буква** (классификация) + **на какой угол повёрнута** (регрессия, для доворота роботом до 0°).
- Подход: **synthetic on-the-fly** (cut-and-paste) — эталоны выровнены в 0°, движок поворачивает на 0–360° (угол = GT-метка), вклеивает на реальный фон ленты, аугментирует. Файлы на диск НЕ пишутся (генерация в DataLoader).
- Сейчас **12 из 33 букв** (Ё А Б В Г Д Е Ж З И Й К) — тестовый набор. Погрешность ручного выравнивания эталонов в 0° = **1–2°** (это потолок точности угла).

## Архитектура цепочки (что аудитить)

```
data/dataset_gen/manual_sprites/<буква>/*.png   (RGBA 128x128, ~8 реальных вырезов: 4 угла × 2 света, выровнены в 0°)
        │
        ▼  Services/dataset_gen  (генератор, synthetic on-the-fly)
   пресет: Services/dataset_gen/presets/manual_letters_disk.yaml
   - поворот 0–360° = GT; вклейка на фон data/backgrounds/belt/ (16 тайлов реальной ленты)
   - симметрия overrides: О→full, Ж/И/Н/Ф/Х→180; object_size_frac 0.72–0.95 (под кроп диска)
   - фотометрия: glare/blur/motion/noise/свет/contact_shadow
        │
        ▼  Services/ml_train  (обучение)
   пресет: Services/ml_train/presets/manual_letters.yaml (боевой) + manual_letters_smoke.yaml (смоук)
   - mobilenet_v3_large + angle_head (sin,cos), AMP bf16, EMA, cosine, early-stopping
   - encode/decode угла: factor=2 для symmetry=180 (Services/dataset_gen/core/symmetry.py)
   - экспорт → ONNX + sidecar (data/models/<run>.onnx + .yaml + _classes.txt)
        │
        ▼  Services/ml_inference  (инференс в pipeline GUI)
   plugin: Services/ml_inference/plugin/plugin.py + engine.py + core/postprocess.py
   - 2 выхода: logits → argmax → буква; angle (sin,cos) → decode_angle → θ + angle_valid
   - симметрия из sidecar: О → angle_valid=False (робот не доворачивает); Ж/И → θ mod 180
```

## Done

- **Пресеты созданы и провалидированы** (preview-сетка отрисована корректно: углы, реальная лента, контактная тень, маркеры [180] у Ж/И):
  - `Services/dataset_gen/presets/manual_letters_disk.yaml` (генератор)
  - `Services/ml_train/presets/manual_letters.yaml` (large, боевой) + `manual_letters_smoke.yaml` (small, смоук)
- **Фон нарезан** из 2 чистых кадров ленты → `data/backgrounds/belt/` (16 тайлов; `_cover_crop` масштабирует+рандом-кропает).
- **Обучена модель** (mobilenet_v3_large, GPU CUDA bf16, early-stop на эпохе 18). Метрики (валидация, синтетика):
  - `balanced_accuracy = 0.985`
  - `angle_mae_deg = 2.28°` (у потолка выравнивания 1–2°)
  - `angle_within_5deg = 0.92` (92% дисков точнее 5° — ключевая цифра для робота)
  - `angle_p95_deg = 5.77°`; худший класс — З (3.34°)
  - Экспорт OK: `data/models/mobilenet_v3_large_20260615_112355.onnx` + sidecar, parity torch↔onnx Δ=2e-6.
- **Латентность замерена** (engine.predict, CPU onnxruntime): **mean 3.27 ms / ~306 FPS**, p95 4.36 ms. GPU для инференса не нужен.
- **Телеметрия латентности расширена в плагине** (было только `avg_latency_ms`): добавлены `last_latency_ms`, `max_latency_ms`, `inference_fps`. **Тесты: 11/11 проходят** (`Services/ml_inference/tests/test_plugin.py`).

## What did NOT work / грабли (НЕ повторять)

- **torch ставился `+cpu`** хотя GPU есть (RTX 3050 4GB, драйвер CUDA 12.6). Дефолтный PyPI на Windows всегда отдаёт `+cpu`. Фикс: `uv pip install --reinstall torch torchvision --index https://download.pytorch.org/whl/cu124` → `torch 2.6.0+cu124`. **`uv sync` откатит обратно на +cpu** (источник не закреплён в pyproject).
- **`uv pip install` падает с «Отказано в доступе» на `_imaging.pyd`**, если запущен Python-процесс, держащий Pillow (прототип/REPL). Лечится: закрыть процесс → повторить (колёса в кэше).
- **`.venv` без модуля pip** (uv-venv): `python -m pip` → «No module named pip». Ставить только через `uv pip`. Install-команды запускает ПОЛЬЗОВАТЕЛЬ (deny-правило на pip), агент даёт команду.
- **onnxruntime — CPU-only** (`providers: [Azure, CPU]`, нет CUDAExecutionProvider). Регистр `device: cuda` в плагине для ONNX ничего не даст без `onnxruntime-gpu`. При 3 мс на CPU — не нужно.
- **cv2.imread/imwrite не умеют кириллические пути на Windows** — dataset_gen использует imread_unicode/imwrite_unicode. Консольный print стрелки `→` падает под cp1251 → ставить `PYTHONIOENCODING=utf-8`.

## Key decisions made

- **mobilenet_v3_large** (не small/v4): для робота критична точность угла; крупный backbone → ниже angle_mae. Классификация всё равно тривиальна. На инференсе диск идёт по одному → скорость не узкое место.
- **synthetic on-the-fly**, не экспорт файлов: train/val независимые сиды, разнообразнее, без хранения.
- **Реальный фон ленты** (не процедурный/null): закрывает domain-shift на кольце фона у края диска (инференс кропает диск по кругу).
- **batch_size 32** (не 64) под 4GB VRAM.
- **monitor: balanced_accuracy** (не angle_mae): неверная буква = катастрофа для робота. Угол смотрим в metrics.json. При насыщении классификации можно переключить на angle_mae_deg.

## Замечания для аудита (на что смотреть критически)

1. **resize-политика**: обучение — stretch (`v2.Resize`), ml_inference.preprocess по умолчанию — letterbox (паддинг 114). Для квадратных кропов диска разницы нет, для неквадратного ROI политики разойдутся. Проверить, что на инференс подаётся квадратный кроп.
2. **Контракт угла train↔inference**: encode factor=2 для symmetry=180. Убедиться, что decode_angle в ml_inference/postprocess строго обратен encode_angle dataset_gen (единый источник — symmetry.py).
3. **angle_valid для full-симметрии (О)**: при пустом/без-угла top-1 плагин ОБЯЗАН сбрасывать angle_valid (иначе робот доворачивает по stale-углу). Проверено в коде — перепроверить логику `_update_last_pred_telemetry`.
4. **Валидация только на синтетике** — реальной проверки на отложенных фото ещё НЕ было. Это главный риск (domain shift). 92%@5° на синтетике ≠ на реальной ленте.
5. **12 из 33 букв** — итог не финальный; на 33 классах перепроверить confusion_matrix (похожие глифы).
6. **thread_safe=False** у плагина (ONNX InferenceSession) — проверить, что pipeline не зовёт process() параллельно.

## Test results (сводка)

- `Services/ml_inference/tests/test_plugin.py` — **11/11 passed** (вкл. 2 новых на latency-телеметрию).
- Обучение: смоук (small, CPU, 10эп) bal_acc 0.95 / angle 23°; боевой (large, GPU, early-stop@18) bal_acc 0.985 / angle 2.28° / within5° 0.92.
- Латентность: 3.27 ms mean (CPU onnxruntime).
- Прочие тесты ml_train/dataset_gen в этой сессии НЕ прогонялись целиком — стоит прогнать в аудите.

## Next step

В новом чате: прогнать полный аудит цепочки — начать с `pytest Services/dataset_gen/tests Services/ml_train/tests Services/ml_inference/tests` (зафиксировать что зелено), затем по пунктам «Замечания для аудита» проверить контракт угла encode↔decode, resize-политику и stale-angle, и выдать список замечаний с приоритетами.

## Files changed (эта сессия)

Изменены:
- `Services/ml_inference/plugin/plugin.py` (+last/max latency, inference_fps, _publish_state(elapsed))
- `Services/ml_inference/plugin/registers.py` (+3 readonly-поля телеметрии)
- `Services/ml_inference/tests/test_plugin.py` (+2 теста телеметрии)
- `docs/claude/memory/MEMORY.md` (+3 записи)

Созданы:
- `Services/dataset_gen/presets/manual_letters_disk.yaml`
- `Services/ml_train/presets/manual_letters.yaml`, `manual_letters_smoke.yaml`
- `data/backgrounds/belt/*.png` (16 тайлов), `preview_manual.png`, `preview_belt.png`
- Модель: `data/models/mobilenet_v3_large_20260615_112355.{onnx,yaml,_classes.txt}` + прогон `data/ml_train/runs/mobilenet_v3_large_20260615_112355/`
- Память: `docs/claude/memory/{project_cuda_torch_setup,feedback_package_install_by_user,project_letter_angle_training}.md`
