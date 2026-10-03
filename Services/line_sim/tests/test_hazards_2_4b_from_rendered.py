"""Task 2.4b, hazard автора: `LayeredObject.from_rendered` держит обещание класса «read-only RGBA».

Опасность: `RenderedObject` можно собрать руками с записываемым массивом (база `layer_render` сама
ставит `writeable=False`, но тип этого не требует). `from_rendered` не копирует массив, поэтому обязан
сам закрыть запись — иначе `render()` отдаёт потребителю ленты изменяемый кэш объекта.
"""

from __future__ import annotations

import numpy as np

from Services.layer_render.factory import RenderedObject
from Services.line_sim.core.layered_object import LayeredObject


def test_from_rendered_makes_a_hand_built_writable_array_read_only_without_copy():
    rgba = np.zeros((4, 4, 4), dtype=np.uint8)
    assert rgba.flags.writeable is True  # предусловие: массив записываемый
    rendered = RenderedObject(rgba=rgba, class_name="c", angle_deg=0.0, defect=None, layer_params={})

    obj = LayeredObject.from_rendered(rendered, object_id="o-1", spawn_encoder=1.0)

    out = obj.render()
    assert out is rendered.rgba  # копии нет
    assert out.flags.writeable is False
