"""Apply one injection's text edits in the worktree (CRLF-aware). Usage: inj_edit.py I<n>"""

import sys

PMP = "multiprocess_framework/modules/process_manager_module/process/process_manager_process.py"
CPS = "multiprocess_framework/modules/process_manager_module/core/child_process_stop.py"
REG = "multiprocess_framework/modules/process_manager_module/core/process_registry.py"
ORC = "multiprocess_prototype/orchestrator.py"

E = {}

E["I1"] = [
    (
        PMP,
        "            if cmd_name in self._LIFECYCLE_COMMANDS:\n"
        '                routing = {"executor": "pm-lifecycle-submit", **self._LIFECYCLE_COMMANDS[cmd_name]}\n',
        "            if cmd_name in self._LIFECYCLE_COMMANDS:\n"
        "                routing = {}  # INJ I1: class L without executor\n",
    ),
    (
        ORC,
        '            routing = {"executor": "pm-lifecycle-submit", "targets": "all"} if cmd_name == "recipe.activate" else {}\n',  # noqa: E501
        "            routing = {}  # INJ I1\n",
    ),
]

E["I2"] = [
    (
        PMP,
        '            "pm-lifecycle", {"kind": "keyed", "serial": True}, should_reject=self._pm_stopping\n        )\n',
        '            "pm-lifecycle", {"kind": "keyed", "serial": True}, should_reject=None\n'
        "        )\n"
        "        self._lifecycle_executor.request_stop = lambda: None  # INJ I2\n",
    ),
]

E["I3"] = [
    (
        CPS,
        "            if self._abort_requested():\n                # Метки выжившим нет;",
        "            if False and self._abort_requested():  # INJ I3\n                # Метки выжившим нет;",
    ),
]

E["I3b"] = [
    (
        CPS,
        "            if self._aborted or self._kill_started_at is not None:\n",
        "            if self._kill_started_at is not None:  # INJ I3b\n",
    ),
]

E["I4"] = [
    (
        PMP,
        "        if key is not None:\n            key = frozenset(key)\n        self._shift(key, +1)\n",
        "        if key is not None:\n"
        "            key = frozenset(key)\n"
        "        # INJ I4: immediate success reply, executor gets a no-op reply\n"
        '        reply({"success": True, "process_name": (next(iter(key)) if key else None)})\n'
        "        reply = lambda _result: None  # noqa: E731\n"
        "        self._shift(key, +1)\n",
    ),
]

E["I5"] = [
    (
        PMP,
        "                result = self.command_manager.handle_command(inner_msg, reply=reply)\n",
        "                result = self.command_manager.handle_command(inner_msg)  # INJ I5: no reply -> in place\n",
    ),
]

E["I6"] = [
    (
        PMP,
        "        if busy:\n            return submit.submit(action, key, reply)\n",
        "        if False and busy:  # INJ I6\n            return submit.submit(action, key, reply)\n",
    ),
]

I7_COMMON_READERS = [
    (
        PMP,
        "        result = self._topology_manager.get()\n",
        "        self._ensure_routing_state()\n"
        "        with self._routing_lock:  # INJ I7\n"
        "            result = self._topology_manager.get()\n",
    ),
    (
        PMP,
        "        for wire_key, info in list(self._active_wires.items()):\n",
        "        self._ensure_routing_state()\n"
        "        with self._routing_lock:  # INJ I7\n"
        "            _inj_snap = list(self._active_wires.items())\n"
        "        for wire_key, info in _inj_snap:\n",
    ),
]
# I7: literal. _routing_lock is a plain Lock -> the action takes it itself inside -> self-deadlock,
# so it becomes an RLock (both creation sites). The whole operation runs under it.
E["I7"] = [
    (
        PMP,
        "        self._incarnations: dict[str, int] = {}\n        self._routing_lock = threading.Lock()\n",
        "        self._incarnations: dict[str, int] = {}\n        self._routing_lock = threading.RLock()  # INJ I7\n",
    ),
    (
        PMP,
        '        if not hasattr(self, "_routing_lock"):\n            self._routing_lock = threading.Lock()\n',
        '        if not hasattr(self, "_routing_lock"):\n            self._routing_lock = threading.RLock()  # INJ I7\n',  # noqa: E501
    ),
    (
        PMP,
        "        try:\n"
        "            return self._executor.submit(action, key, counted_reply, inline_if_idle=inline_if_idle)\n",
        "        inner_action = action\n"
        "\n"
        "        def locked_action() -> Any:  # INJ I7: whole operation under _routing_lock\n"
        "            with self._pm._routing_lock:\n"
        "                return inner_action()\n"
        "\n"
        '        locked_action.__name__ = getattr(inner_action, "__name__", "action")\n'
        "        try:\n"
        "            return self._executor.submit(locked_action, key, counted_reply, inline_if_idle=inline_if_idle)\n",
    ),
] + I7_COMMON_READERS
# I7b (extra, diagnostic): same idea but a dedicated RLock, so the door _shift(+1) is not blocked.
E["I7b"] = [
    (PMP, "class _LifecycleSubmit:\n", "_INJ7B_LOCK = threading.RLock()  # INJ I7b\n\n\nclass _LifecycleSubmit:\n"),
    (
        PMP,
        "        try:\n"
        "            return self._executor.submit(action, key, counted_reply, inline_if_idle=inline_if_idle)\n",
        "        inner_action = action\n"
        "\n"
        "        def locked_action() -> Any:  # INJ I7b\n"
        "            with _INJ7B_LOCK:\n"
        "                return inner_action()\n"
        "\n"
        '        locked_action.__name__ = getattr(inner_action, "__name__", "action")\n'
        "        try:\n"
        "            return self._executor.submit(locked_action, key, counted_reply, inline_if_idle=inline_if_idle)\n",
    ),
    (
        PMP,
        "        result = self._topology_manager.get()\n",
        "        with _INJ7B_LOCK:  # INJ I7b\n            result = self._topology_manager.get()\n",
    ),
    (
        PMP,
        "        for wire_key, info in list(self._active_wires.items()):\n",
        "        with _INJ7B_LOCK:  # INJ I7b\n"
        "            _inj_snap = list(self._active_wires.items())\n"
        "        for wire_key, info in _inj_snap:\n",
    ),
    (
        PMP,
        '            incarnations = dict(self._incarnations)\n        mon = getattr(self, "_process_monitor", None)\n',
        "            incarnations = dict(self._incarnations)\n"
        "        with _INJ7B_LOCK:  # INJ I7b\n"
        "            pass\n"
        '        mon = getattr(self, "_process_monitor", None)\n',
    ),
]

E["I8"] = [
    (
        PMP,
        "            if cmd_name in self._LIFECYCLE_COMMANDS:\n"
        '                routing = {"executor": "pm-lifecycle-submit", **self._LIFECYCLE_COMMANDS[cmd_name]}\n',
        '            if cmd_name == "system.shutdown":  # INJ I8\n'
        '                routing = {"executor": "pm-lifecycle-submit", "targets": "all"}\n'
        "            elif cmd_name in self._LIFECYCLE_COMMANDS:\n"
        '                routing = {"executor": "pm-lifecycle-submit", **self._LIFECYCLE_COMMANDS[cmd_name]}\n',
    ),
]

E["I9"] = [
    (
        PMP,
        '"pm-lifecycle", {"kind": "keyed", "serial": True}',
        '"pm-lifecycle", {"kind": "keyed", "serial": False}',
    ),  # INJ I9
]

E["I10"] = [
    (
        PMP,
        "                self._stop_lifecycle_executor(deadline)\n            finally:\n",
        "                # INJ I10: only the queue cut here; the wait moved to join_until\n"
        '                _ex = getattr(pm, "_lifecycle_executor", None)\n'
        "                if _ex is not None:\n"
        "                    _ex.request_stop()\n"
        "            finally:\n",
    ),
    (
        PMP,
        "            raise error\n        if self._group is None and not self._start_failed:\n",
        "            raise error\n"
        "        self._stop_lifecycle_executor(deadline)  # INJ I10\n"
        "        if self._group is None and not self._start_failed:\n",
    ),
]

E["I11"] = [
    (
        PMP,
        "            try:\n                reply(result)\n            finally:\n                release()\n",
        "            try:\n"
        "                reply(result)\n"
        "            finally:\n"
        '                if isinstance(result, dict) and result.get("success") is True:  # INJ I11\n'
        "                    release()\n",
    ),
]

E["I12"] = [
    (
        PMP,
        "        for wire_key, info in list(self._active_wires.items()):\n",
        "        for wire_key, info in self._active_wires.items():  # INJ I12\n",
    ),
]

E["I13"] = [
    (
        REG,
        "self._registry._build_child_stop(list(names), self._mark_reader_gone)\n",
        "self._registry._build_child_stop(\n"
        "                    list(names), self._mark_reader_gone, should_abort=self._registry.stop_abort\n"
        "                )  # INJ I13\n",
    ),
]


def apply(name: str) -> None:
    by_file: dict[str, list] = {}
    for f, old, new in E[name]:
        by_file.setdefault(f, []).append((old, new))
    for f, edits in by_file.items():
        with open(f, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        crlf = "\r\n" in text
        for old, new in edits:
            if crlf:
                old = old.replace("\n", "\r\n")
                new = new.replace("\n", "\r\n")
            n = text.count(old)
            if n != 1:
                print(f"NOT APPLIED {name}: {f}: anchor found {n} times: {old[:70]!r}")
                sys.exit(2)
            text = text.replace(old, new)
        with open(f, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
    print(f"applied {name}: {sorted(by_file)}")


if __name__ == "__main__":
    apply(sys.argv[1])
