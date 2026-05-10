"""Input operations: камеры и видеофайлы."""

from .webcam_input_op import WebcamInputOp
from .hikvision_input_op import HikvisionInputOp
from .file_input_op import FileInputOp
from .simulator_input_op import SimulatorInputOp

__all__ = ["WebcamInputOp", "HikvisionInputOp", "FileInputOp", "SimulatorInputOp"]
