"""Схемы регистров — пакет приложения multiprocess_prototype.registers.schemas."""


def test_registers_schemas_package_exports():
    from multiprocess_prototype.registers.schemas import ProcessorRegisters, RendererRegisters
    from multiprocess_prototype.registers.schemas.processing_tab import (
        ProcessorRegisters as P2,
        RendererRegisters as R2,
    )

    assert ProcessorRegisters is P2
    assert RendererRegisters is R2
    assert ProcessorRegisters.__name__ == "ProcessorRegisters"
    assert RendererRegisters.__name__ == "RendererRegisters"
