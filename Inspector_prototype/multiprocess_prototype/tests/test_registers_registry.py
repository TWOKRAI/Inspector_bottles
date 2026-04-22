# multiprocess_prototype/tests/test_registers_registry.py
"""REGISTER_MODELS и create_registers согласованы одной картой."""

from __future__ import annotations


def test_register_models_matches_create_registers():
    from multiprocess_prototype.registers import REGISTER_MODELS, create_registers
    from multiprocess_prototype.registers.schemas.processing_tab.names import (
        PROCESSOR_REGISTER,
        RENDERER_REGISTER,
    )
    from multiprocess_prototype.registers.schemas.camera_tab.names import CAMERA_REGISTER

    rm, _ = create_registers()
    assert set(rm.register_names()) == set(REGISTER_MODELS)
    assert set(REGISTER_MODELS) == {CAMERA_REGISTER, PROCESSOR_REGISTER, RENDERER_REGISTER}
