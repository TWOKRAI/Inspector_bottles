"""Тестовые дублёры robot_comm (без сети/pymodbus)."""

from Services.robot_comm.testing.fake_transport import FakeRobotTransport

__all__ = ["FakeRobotTransport"]
