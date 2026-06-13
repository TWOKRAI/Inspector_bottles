# -*- coding: utf-8 -*-
"""Тесты CalibrationPresenter — правильные команды cal_* в target-процесс."""

from __future__ import annotations

from multiprocess_prototype.frontend.widgets.tabs.services.robot.calibration.presenter import (
    CalibrationPresenter,
)


class FakeSender:
    def __init__(self):
        self.calls = []

    def request_command(self, process, command, args):
        self.calls.append((process, command, args))
        return {"status": "accepted"}


class FakeRunner:
    def submit(self, fn, on_result=None):
        result = fn()
        if on_result:
            on_result(result)


def _presenter(target="cal"):
    sender = FakeSender()
    p = CalibrationPresenter(command_sender=sender, request_runner=FakeRunner(), target_process=target)
    return p, sender


def test_begin_sends_ids():
    p, sender = _presenter()
    p.begin("cam0", "robot_main", "vfd_belt")
    assert sender.calls == [("cal", "cal_begin", {"camera_id": "cam0", "robot_id": "robot_main", "vfd_id": "vfd_belt"})]


def test_each_command_routed_to_target():
    p, sender = _presenter(target="calib_proc")
    p.capture_image()
    p.set_robot_point(2)
    p.encoder_scale(0)
    p.belt_run(12.5)
    p.belt_stop()
    p.compute()
    p.save()
    p.reset()
    cmds = [(proc, cmd, args) for proc, cmd, args in sender.calls]
    assert cmds == [
        ("calib_proc", "cal_capture_image", {}),
        ("calib_proc", "cal_set_robot_point", {"index": 2}),
        ("calib_proc", "cal_encoder_scale", {"ref_index": 0}),
        ("calib_proc", "cal_belt_run", {"freq": 12.5}),
        ("calib_proc", "cal_belt_stop", {}),
        ("calib_proc", "cal_compute", {}),
        ("calib_proc", "cal_save", {}),
        ("calib_proc", "cal_reset", {}),
    ]


def test_on_result_callback_receives_ack():
    p, _ = _presenter()
    received = []
    p.capture_image(on_result=received.append)
    assert received == [{"status": "accepted"}]


def test_no_sender_no_crash():
    p = CalibrationPresenter(command_sender=None, request_runner=None, target_process="cal")
    received = []
    p.compute(on_result=received.append)
    assert received == [{}]  # graceful: пустой dict
