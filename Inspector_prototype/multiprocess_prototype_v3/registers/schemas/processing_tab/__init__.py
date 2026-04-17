"""Redirect: registers.schemas.processing_tab → registers.names + registers.processor_registers."""

from multiprocess_prototype_v3.registers.names import (
    PROCESSOR_REGISTER,
    RENDERER_REGISTER,
)

__all__ = [
    "PROCESSOR_REGISTER",
    "RENDERER_REGISTER",
]
