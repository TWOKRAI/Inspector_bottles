# multiprocess_prototype\tests\test_shared_memory.py
"""
Тест SharedMemory изолированно (Этап 8.2).

Проверяет write/read кадров через SharedResourcesManager.
Запуск: PYTHONPATH="Inspector_prototype:Inspector_prototype/multiprocess_framework/modules" python -m multiprocess_prototype.tests.test_shared_memory
"""

import numpy as np
import pytest


def test_shared_memory_write_read():
    """SharedMemory: запись и чтение кадра через SRM."""
    from multiprocess_framework.modules.shared_resources_module import (
        SharedResourcesManager,
    )
    from multiprocess_prototype.utils.frame_generator import FrameGenerator

    srm = SharedResourcesManager(manager_name="test_srm")
    srm.initialize()

    mm = srm.memory_manager
    mm.create_memory_dict(
        "test",
        {"test_frame": (1, (480, 640, 3), "uint8")},
        coll=2,
    )

    gen = FrameGenerator(640, 480)
    frame = gen.generate_frame()

    # Запись
    result = mm.write_images("test", "test_frame", [frame], 0)
    assert result is not None, "write_images должен вернуть shm name"

    # Чтение
    images = mm.read_images("test", "test_frame", 0, n=1)
    assert images is not None
    assert len(images) == 1
    assert images[0].shape == (480, 640, 3)
    assert np.array_equal(frame, images[0]), "Прочитанный кадр должен совпадать с записанным"

    mm.close_all("test")
    srm.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
