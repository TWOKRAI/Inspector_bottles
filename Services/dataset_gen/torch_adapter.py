"""Режим вывода №2: on-the-fly генерация для PyTorch DataLoader.

Импортируется лениво через Services.dataset_gen.__getattr__ — torch
не обязателен для остального сервиса (экспорт/preview работают без него).

Детерминизм с num_workers: __getitem__ строит собственный rng из (seed, idx),
поэтому сэмпл idx одинаков независимо от числа воркеров и порядка обхода.
"""

from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import Dataset

from Services.dataset_gen.interfaces import SampleGenerator


class SyntheticDataset(Dataset):
    """torch Dataset поверх SampleGenerator (генерация на лету, без файлов.

    Эпоха = length сэмплов; классы чередуются (idx % num_classes) —
    равномерный баланс без сэмплера.

    __getitem__ возвращает (image, target):
      image  — float32 CHW, [0..1] (до transform);
      target — dict тензоров: class_index (long), angle (float32, [sin, cos]),
               angle_valid (bool) — маска loss по углу.
    """

    def __init__(
        self,
        generator: SampleGenerator,
        length: int | None = None,
        seed: int = 0,
        transform=None,
    ) -> None:
        """Pre:
        - length ≥ 1 либо None (тогда берётся frames_per_class * num_classes,
          если у генератора есть config, иначе 1000 * num_classes)
        """
        self._generator = generator
        self._seed = int(seed)
        self._transform = transform
        if length is None:
            frames = getattr(getattr(generator, "config", None), "output", None)
            per_class = frames.frames_per_class if frames is not None else 1000
            length = per_class * generator.num_classes
        if length < 1:
            raise ValueError(f"length должен быть >= 1, получено {length}")
        self._length = int(length)

    def __len__(self) -> int:
        return self._length

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
        """Post:
        - image.shape == (3, H, W), dtype float32 (до transform)
        - target["angle"]: sin²+cos²==1 при angle_valid, иначе нули
        """
        if not 0 <= idx < self._length:
            raise IndexError(idx)
        # независимый поток случайности на сэмпл: воспроизводимо при num_workers>0
        rng = np.random.default_rng((self._seed, idx))
        class_index = idx % self._generator.num_classes
        frame, label = self._generator.generate_sample(class_index, rng)

        image = torch.from_numpy(frame.copy()).permute(2, 0, 1).float() / 255.0
        if self._transform is not None:
            image = self._transform(image)
        target = {
            "class_index": torch.tensor(label.class_index, dtype=torch.long),
            "angle": torch.tensor([label.angle_sin, label.angle_cos], dtype=torch.float32),
            "angle_valid": torch.tensor(label.angle_valid, dtype=torch.bool),
        }
        return image, target
