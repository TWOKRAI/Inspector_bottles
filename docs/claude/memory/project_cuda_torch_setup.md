---
name: project-cuda-torch-setup
description: Стенд RTX 3050 4GB; torch для ml_train должен быть cu124-колесом, не +cpu
metadata:
  type: project
---

Стенд обучения: **NVIDIA RTX 3050 Laptop, 4 ГБ VRAM**, драйвер 561.09 (CUDA 12.6), bf16 поддерживается.

GPU есть, но `[ml-train]` ставит torch с дефолтного PyPI → на Windows это всегда `+cpu` (`cuda.is_available()=False`). Лечится переустановкой cu124-колеса:

```
uv pip install --reinstall torch torchvision --index https://download.pytorch.org/whl/cu124
```

cu124-индекс отдаёт `torch 2.6.0+cu124` / `torchvision 0.21.0+cu124` (ниже `torch>=2.11` из pyproject, но работает). AMP идёт в bf16 (Ampere). На 4 ГБ для mobilenet_v3_large @128px ставить `batch_size: 32` (64 → риск OOM при ~2 ГБ занятых дисплеем).

**Грабли:** `uv sync` откатывает torch обратно на `+cpu` (cu124-источник не закреплён в pyproject). Если нужна стойкость — прописать torch с cu124-индексом в `[tool.uv.index]`/`[tool.uv.sources]`. **При переустановке Pillow `uv` падает с «Отказано в доступе» на `_imaging.pyd`, если запущен Python-процесс, держащий Pillow (прототип/REPL) — закрыть его и повторить (колёса в кэше).** См. [[feedback-package-install-by-user]], [[project-ml-train-service]], [[project-dataset-gen-service]].
