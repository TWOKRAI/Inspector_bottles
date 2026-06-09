# data/models — веса моделей + sidecar-метаданные

Папка для весов нейросетей и их описаний. Сервис `Services/ml_inference` сканирует её
и формирует каталог доступных моделей для выпадающего списка в GUI.

## Конвенция: веса + sidecar

Каждая модель — это **два файла рядом**:

```
data/models/
├── mobilenetv3_large.onnx        # веса
├── mobilenetv3_large.yaml        # sidecar-метаданные (тот же basename)
├── imagenet_classes.txt          # labels (опц., общий для нескольких моделей)
└── ...
```

`ModelRegistry` сопоставляет веса (`*.onnx`, `*.pt`) с одноимённым `*.yaml`.
Если sidecar отсутствует — модель **игнорируется** (нет метаданных препроцессинга).

## Формат sidecar (`<basename>.yaml`)

```yaml
name: "MobileNetV3-Large (ImageNet)"   # человекочитаемое имя для GUI
task: classification                    # classification | detection (задел)
backend: onnx                           # onnx | torch
weights: mobilenetv3_large.onnx         # имя файла весов (относительно этой папки)
input_size: [224, 224]                  # [H, W] входа сети
layout: NCHW                            # NCHW | NHWC
color: RGB                              # RGB | BGR — порядок каналов на входе сети
normalize:                              # нормализация: (pixel/255 - mean) / std
  mean: [0.485, 0.456, 0.406]
  std:  [0.229, 0.224, 0.225]
labels: imagenet_classes.txt            # файл меток (опц.); без него — "class_<id>"
```

**Почему так:** препроцессинг (resize, цветопорядок, нормализация, layout) задаётся
данными, а не кодом. Добавить новую модель = положить веса + sidecar, править код не нужно.

## Где взять MobileNetV3 в ONNX

Экспорт из torchvision (нужен `pip install '.[ml-torch]'`):

```python
import torch, torchvision
m = torchvision.models.mobilenet_v3_large(weights="IMAGENET1K_V2").eval()
dummy = torch.randn(1, 3, 224, 224)
torch.onnx.export(m, dummy, "data/models/mobilenetv3_large.onnx",
                  input_names=["input"], output_names=["logits"],
                  dynamic_axes={"input": {0: "batch"}}, opset_version=13)
```

Файл `imagenet_classes.txt` (1000 строк, по классу на строку) берётся из репозитория
torchvision / pytorch hub. Без него постобработка вернёт `class_<id>` вместо имён.

> Веса в git **не коммитятся** (см. `.gitignore`) — кладутся локально/на стенде.
