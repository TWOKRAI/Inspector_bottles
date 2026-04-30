"""Blueprint: Color Mask Demo — вебкамера + HSV-маска + рендер.

Чертёж системы (SchemaBase):
    camera_0    →  processor_0    →  renderer
    [capture]      [color_mask]      [render]

Всё SchemaBase — сериализуемый, валидируемый, редактируемый в UI.
"""

from multiprocess_framework.modules.process_module.generic.blueprint import (
    ProcessConfig,
    SystemBlueprint,
    Wire,
)

from multiprocess_prototype.backend.plugins.capture.config import CapturePluginConfig
from multiprocess_prototype.backend.plugins.color_mask.config import ColorMaskPluginConfig
from multiprocess_prototype.backend.plugins.render.config import RenderPluginConfig


BLUEPRINT = SystemBlueprint(
    name="color_mask_demo",
    description="Вебкамера \u2192 HSV-маска по цвету \u2192 overlay рендер",
    processes=[
        ProcessConfig.from_plugins(
            "camera_0",
            CapturePluginConfig(
                camera_id=0,
                device_id=0,
                fps=25,
                resolution_width=640,
                resolution_height=480,
                ring_buffer_size=3,
            ),
            priority="high",
        ),
        ProcessConfig.from_plugins(
            "processor_0",
            ColorMaskPluginConfig(
                camera_id=0,
                h_min=35, h_max=85,
                s_min=50, s_max=255,
                v_min=50, v_max=255,
                resolution_width=640,
                resolution_height=480,
            ),
            # Цепочка — добавить ещё плагины:
            # BlurPluginConfig(kernel=5),
        ),
        ProcessConfig.from_plugins(
            "renderer",
            RenderPluginConfig(
                camera_id=0,
                mask_alpha=0.5,
                mask_color_b=0,
                mask_color_g=255,
                mask_color_r=0,
                resolution_width=640,
                resolution_height=480,
            ),
        ),
    ],
    wires=[
        Wire(
            source="camera_0.capture.frame",
            target="processor_0.color_mask.frame",
            description="Кадр с камеры \u2192 обработка",
        ),
        Wire(
            source="processor_0.color_mask.mask",
            target="renderer.render.mask",
            description="Маска \u2192 рендер",
        ),
        Wire(
            source="camera_0.capture.frame",
            target="renderer.render.frame",
            description="Исходный кадр \u2192 рендер (для overlay)",
        ),
    ],
)
