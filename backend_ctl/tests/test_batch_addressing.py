# -*- coding: utf-8 -*-
"""Task 5.4, ось процессов: одна команда — M процессов, ответ per-process.

Проверяется ровно то, что заявлено спекой, по одному свойству на тест:

  * точное имя в батч-ветку НЕ заходит (бит-в-бит прежний путь и прежняя форма);
  * ``all`` / узор / список раскрываются по ЖИВОЙ топологии;
  * ответ несёт секцию на каждый адресованный процесс;
  * пустое раскрытие — отказ с перечнем топологии, а не тихий успех;
  * имя вне топологии названо (``unknown``), а не выпало из списка молча;
  * больной процесс не роняет батч и отличим от ответившего отказом.
"""

from __future__ import annotations

from typing import Any, Dict, List

from backend_ctl.driver import BackendDriver


def _driver_with_topology(monkeypatch, procs: List[str], *, answers: Dict[str, Any] | None = None):
    """Драйвер с подставным ``send_command``: топология + журнал адресатов."""
    d = BackendDriver()
    sent: List[tuple] = []
    answers = answers or {}

    def fake_send(target: str, command: str, args: Any = None, *, timeout: Any = None) -> Dict[str, Any]:
        sent.append((target, command, args))
        if command == "state.get_subtree":
            return {"success": True, "result": {"subtree": {p: {} for p in procs}}}
        answer = answers.get(target)
        if isinstance(answer, BaseException):
            raise answer
        if answer is not None:
            return answer
        # Форма реального ответа: конверт + лист хендлера, и лист НЕСЁТ свой success
        # (именно так отвечает `_toggle_one_sink`). Лист без него — отдельный случай,
        # он проверяется тестом ниже.
        return {
            "success": True,
            "result": {"success": True, "process": target, "sink": (args or {}).get("sink")},
        }

    monkeypatch.setattr(d, "send_command", fake_send)
    return d, sent


class TestExactNameUnchanged:
    def test_exact_name_does_not_enter_the_batch_branch(self, monkeypatch) -> None:
        """Точное имя: ни round-trip'а за топологией, ни новой формы ответа.

        Гарантия «бит-в-бит прежнее» стоит на одном вопросе `_is_process_batch`.
        Проверяется НАБЛЮДАЕМЫМ следствием — какие команды ушли на провод: спрос
        топологии здесь означал бы, что адресный путь стал платить за батч.
        """
        d, sent = _driver_with_topology(monkeypatch, ["camera_0", "camera_1"])
        res = d.logger_sink_disable("camera_0", "module_trace")
        assert [c for _t, c, _a in sent] == ["logger.sink.disable"], "адресный путь спросил лишнее"
        assert "batch" not in res, f"адресный ответ приобрёл батч-форму: {res}"
        assert res["process"] == "camera_0"


class TestExpansion:
    def test_all_reaches_every_live_process(self, monkeypatch) -> None:
        d, sent = _driver_with_topology(monkeypatch, ["camera_0", "camera_1", "gui"])
        res = d.logger_sink_disable("all", "module_trace")
        assert res["batch"] is True
        assert sorted(res["targets"]) == ["camera_0", "camera_1", "gui"]
        assert sorted(res["processes"]) == ["camera_0", "camera_1", "gui"]
        assert sorted(t for t, c, _a in sent if c == "logger.sink.disable") == ["camera_0", "camera_1", "gui"]

    def test_pattern_selects_a_subset_and_leaves_the_rest_alone(self, monkeypatch) -> None:
        d, sent = _driver_with_topology(monkeypatch, ["camera_0", "camera_1", "gui"])
        res = d.logger_sink_disable("camera_*", "module_trace")
        assert res["targets"] == ["camera_0", "camera_1"]
        assert "gui" not in [t for t, c, _a in sent if c == "logger.sink.disable"]

    def test_explicit_list_is_addressed_as_given(self, monkeypatch) -> None:
        d, _sent = _driver_with_topology(monkeypatch, ["camera_0", "camera_1", "gui"])
        res = d.logger_sink_enable(["gui", "camera_1"], "module_trace")
        assert sorted(res["targets"]) == ["camera_1", "gui"]

    def test_answer_carries_a_section_per_process(self, monkeypatch) -> None:
        """Приёмка задачи буквально: ответ per-process, а не одно сводное число."""
        d, _sent = _driver_with_topology(monkeypatch, ["camera_0", "camera_1"])
        res = d.config_reload("all", observability={"log_level": "DEBUG"})
        assert set(res["processes"]) == {"camera_0", "camera_1"}
        assert all(isinstance(section, dict) for section in res["processes"].values())


class TestNoSilentCaps:
    def test_pattern_matching_nothing_is_a_loud_refusal(self, monkeypatch) -> None:
        """«Раздал в никуда» не имеет права выглядеть как «раздал»."""
        d, sent = _driver_with_topology(monkeypatch, ["camera_0", "gui"])
        res = d.logger_sink_disable("robot_*", "module_trace")
        assert res["success"] is False
        assert res["targets"] == []
        assert "camera_0" in res["error"] and "gui" in res["error"], "отказ не назвал живую топологию"
        assert [c for _t, c, _a in sent] == ["state.get_subtree"], "команда всё-таки ушла на провод"

    def test_name_outside_topology_is_named_not_dropped(self, monkeypatch) -> None:
        d, _sent = _driver_with_topology(monkeypatch, ["camera_0"])
        res = d.logger_sink_disable(["camera_0", "robot"], "module_trace")
        assert res["unknown"] == ["robot"]
        assert res["targets"] == ["camera_0"]
        assert res["success"] is False, "промах по имени обязан снимать общий успех"


class TestOneSickProcess:
    def test_exception_does_not_bring_the_batch_down(self, monkeypatch) -> None:
        """Форма ``system_overview``: исключение возвращается ЗНАЧЕНИЕМ."""
        d, _sent = _driver_with_topology(
            monkeypatch,
            ["camera_0", "camera_1"],
            answers={"camera_1": TimeoutError("нет ответа")},
        )
        res = d.logger_sink_disable("all", "module_trace")
        assert res["failed"] == ["camera_1"]
        assert res["processes"]["camera_0"]["success"] is True, "здоровый сосед пострадал"
        assert "TimeoutError" in res["processes"]["camera_1"]["error"]
        assert res["success"] is False

    def test_success_is_read_the_same_way_as_by_the_addressed_wrappers(self, monkeypatch) -> None:
        """Лист без ``success`` при успешном конверте — не отказ.

        Найдено собственным тестом: батч читал успех только из листа, а `success`
        живёт то в листе, то в конверте — второе прочтение этого различия разошлось
        бы с первым (`_is_ok` в адресных обёртках). Здоровый процесс попадал в
        ``not_ok``, то есть сводка врала бы ровно в спокойном случае.
        """
        d, _sent = _driver_with_topology(
            monkeypatch,
            ["camera_0"],
            answers={"camera_0": {"success": True, "result": {"process": "camera_0"}}},
        )
        res = d.logger_sink_disable("all", "module_trace")
        assert res["not_ok"] == [], f"лист без success принят за отказ: {res}"
        assert res["success"] is True

    def test_refusal_is_not_the_same_diagnosis_as_silence(self, monkeypatch) -> None:
        """``not_ok`` (ответил отказом) и ``failed`` (не ответил) лечатся по-разному."""
        d, _sent = _driver_with_topology(
            monkeypatch,
            ["camera_0", "camera_1"],
            answers={"camera_1": {"success": True, "result": {"success": False, "reason": "уже снят"}}},
        )
        res = d.logger_sink_disable("all", "module_trace")
        assert res["not_ok"] == ["camera_1"]
        assert res["failed"] == [], "отказ процесса не должен считаться отсутствием ответа"
