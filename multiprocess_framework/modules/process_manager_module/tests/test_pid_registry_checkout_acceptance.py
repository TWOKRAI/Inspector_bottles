# -*- coding: utf-8 -*-
"""Приёмка D2: pid-реестр разделён по checkout (слепой tester, до реализации).

Контракт глазами пользователя: два клона/ветки одного приложения на одной машине не
должны реапать процессы друг друга, а реестры прежних имён (общее неразделённое имя
``<app>_system_pids.jsonl`` и продуктовое ``inspector_system_pids.jsonl``) нельзя трогать
как «свои».

Как устроено:
- «Второй checkout» — ВТОРАЯ НАСТОЯЩАЯ КОПИЯ пакета ``multiprocess_framework``
  (``shutil.copytree``, не симлинк: через ``resolve()`` симлинк схлопнулся бы в тот же корень).
  Каждая копия запускается отдельным subprocess с ``PYTHONPATH=<каталог копии>``.
- В env КАЖДОГО subprocess заданы ``TMPDIR``/``TEMP``/``TMP`` = изолированный каталог теста:
  подмена ``tempfile.gettempdir`` в родителе в ребёнка не переходит.
- Жертвы — настоящие subprocess; живость — ``Popen.poll() is None`` (не ``pid_exists``: зомби
  ещё «существует»).
- Одновременный старт — файл-сигнал с рукопожатием «готов»: ``multiprocessing.Barrier`` между
  независимыми subprocess с разным ``PYTHONPATH`` недостижим.
- Ожидаемые значения — литералы; из кода под тестом ничего не пересчитывается.

C1..C10 соответствуют критериям приёмки задачи D2 (нумерация в именах классов).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

import multiprocess_framework

#: Корень проверяемого дерева (worktree): пакет лежит в <корень>/multiprocess_framework.
_PKG_DIR = Path(multiprocess_framework.__file__).resolve().parent
_ROOT = _PKG_DIR.parent

#: Все ручки, которые меняют путь реестра или имя приложения — сбрасываются в env детей.
_PID_ENV_KEYS = ("MULTIPROCESS_PID_FILE", "INSPECTOR_PID_FILE", "MPF_APP_NAME", "PYTHONPATH")

_CHILD_TIMEOUT = 120  # сек на один синхронный дочерний запуск (импорт копии ~0,7 с)
_KILL_TIMEOUT = 30  # сек на смерть жертвы после реапа (зомби-реап ~3 с)

_CHILD_SOURCE = r'''
"""Драйвер дочернего процесса. Импорт пакета — из PYTHONPATH (то есть из нужного checkout)."""
import json
import os
import sys
import time

# Первым делом сообщаем СВОЙ pid: в venv на Windows sys.executable — лаунчер, а настоящий
# интерпретатор (этот процесс) — его потомок, и Popen.pid родителя этот pid не показывает.
_pid_file = os.environ.get("HARNESS_PID_FILE")
if _pid_file:
    with open(_pid_file + ".tmp", "w", encoding="utf-8") as _f:
        _f.write(str(os.getpid()))
    os.replace(_pid_file + ".tmp", _pid_file)

cmd = sys.argv[1]

if cmd == "sleep":
    time.sleep(300)
    sys.exit(0)

import multiprocess_framework as mf
from multiprocess_framework.modules.process_manager_module.launcher import pid_registry as pr

if cmd == "path":
    print(json.dumps({"pkg": mf.__file__, "p1": str(pr.pid_file_path()), "p2": str(pr.pid_file_path())}))
elif cmd == "victim":
    pr.register_self()
    time.sleep(300)
elif cmd == "reap":
    lines = []
    killed = pr.reap_and_reset(log=lines.append)
    print(json.dumps({"killed": killed, "lines": lines}))
elif cmd == "race":
    sync, name = sys.argv[2], sys.argv[3]
    open(os.path.join(sync, name + ".ready"), "w").close()
    while not os.path.exists(os.path.join(sync, "go")):
        time.sleep(0.001)
    killed = pr.reap_and_reset()
    pr.register_self()
    tmp = os.path.join(sync, name + ".result.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"killed": killed, "pid": os.getpid()}, f)
    os.replace(tmp, os.path.join(sync, name + ".result"))
    time.sleep(300)
else:
    raise SystemExit("unknown cmd " + cmd)
'''


# --------------------------------------------------------------------------- инфраструктура


def _entries(path: Path) -> list[dict]:
    """Строки реестра как JSON; БИТАЯ строка = ошибка теста (контракт: валидный JSON)."""
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            out.append(json.loads(raw))
    return out


def _pids(path: Path) -> list[int]:
    return [int(e["pid"]) for e in _entries(path)]


def _lenient_pids(path: Path) -> list[int]:
    """Для ожиданий: недописанную строку пропускаем (идёт запись)."""
    out = []
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                out.append(int(json.loads(raw)["pid"]))
            except Exception:  # noqa: BLE001
                continue
    except FileNotFoundError:
        pass
    return out


def _has_pid(line: str, pid: int) -> bool:
    """pid как отдельное число (граница), а не подстрока другого числа."""
    return re.search(rf"(?<!\d){pid}(?!\d)", line) is not None


def _dead_pid() -> int:
    if not psutil.pid_exists(999999):
        return 999999
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class Harness:
    """Окружение одного сценария: свой temp, свои логи, учёт запущенных процессов."""

    def __init__(self, root: Path, checkouts: dict[str, Path], helper: Path, procs: list):
        self.root = root
        self.tmp = root / "tmp"  # TMPDIR/TEMP/TMP всех детей
        self.logs = root / "logs"
        self.tmp.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.checkouts = checkouts
        self.helper = helper
        self._procs = procs
        self._n = 0

    def env(self, checkout: Path | str, app: str | None = "AppOne", **extra: str) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k not in _PID_ENV_KEYS}
        root = self.checkouts[checkout] if isinstance(checkout, str) and checkout in self.checkouts else Path(checkout)
        base["PYTHONPATH"] = str(root)
        for key in ("TMPDIR", "TEMP", "TMP"):
            base[key] = str(self.tmp)
        base["PYTHONUTF8"] = "1"
        if app is not None:
            base["MPF_APP_NAME"] = app
        base.update(extra)
        return base

    def run(self, checkout, *args: str, app: str | None = "AppOne", **extra: str) -> dict:
        """Синхронный дочерний запуск; stdout — JSON в последней строке."""
        proc = subprocess.run(
            [sys.executable, str(self.helper), *args],
            env=self.env(checkout, app, **extra),
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=_CHILD_TIMEOUT,
        )
        assert proc.returncode == 0, f"дочерний {args} упал rc={proc.returncode}\nSTDERR:\n{proc.stderr[-2000:]}"
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def spawn(self, checkout, *args: str, app: str | None = "AppOne", **extra: str) -> subprocess.Popen:
        """Фоновый дочерний процесс; stderr — в файл logs/<n>_<cmd>.err."""
        self._n += 1
        err_path = self.logs / f"{self._n}_{args[0]}.err"
        pid_path = self.logs / f"{self._n}_{args[0]}.pid"
        with open(err_path, "wb") as err:
            proc = subprocess.Popen(
                [sys.executable, str(self.helper), *args],
                env=self.env(checkout, app, HARNESS_PID_FILE=str(pid_path), **extra),
                cwd=str(self.root),
                stdout=subprocess.DEVNULL,
                stderr=err,
            )
        proc._err_path = err_path  # type: ignore[attr-defined]
        self._procs.append(proc)
        # Popen.pid — это pid того, что запустил sys.executable (в venv на Windows — лаунчер).
        # В реестр и в журнал попадает pid настоящего интерпретатора: берём его из файла жертвы.
        proc.real_pid = self._wait_real_pid(proc, pid_path)  # type: ignore[attr-defined]
        return proc

    @staticmethod
    def _wait_real_pid(proc: subprocess.Popen, pid_path: Path, timeout: float = 30.0) -> int:
        """Ждёт, пока хелпер запишет свой os.getpid() (на POSIX он равен proc.pid)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                text = pid_path.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                text = ""
            if text:
                return int(text)
            assert proc.poll() is None, f"хелпер умер до записи своего pid, rc={proc.returncode}"
            time.sleep(0.02)
        pytest.fail(f"хелпер pid={proc.pid} не записал свой pid в {pid_path} за {timeout} с")

    @staticmethod
    def stderr_of(proc: subprocess.Popen) -> str:
        return Path(proc._err_path).read_text(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]

    def reg_path(self, checkout, app: str | None = "AppOne") -> Path:
        return Path(self.run(checkout, "path", app=app)["p1"])

    def victim(self, checkout, app: str | None = "AppOne") -> subprocess.Popen:
        """Живой процесс, записавший себя в реестр своего checkout (register_self в ребёнке)."""
        reg = self.reg_path(checkout, app)
        proc = self.spawn(checkout, "victim", app=app)
        self.wait_registered(reg, proc)
        return proc

    def sleeper(self) -> subprocess.Popen:
        """Живой процесс, который сам в реестр не пишется."""
        proc = self.spawn("a", "sleep", app=None)
        assert proc.poll() is None
        return proc

    @staticmethod
    def wait_registered(reg: Path, proc: subprocess.Popen, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            assert proc.poll() is None, f"жертва умерла до записи в реестр, rc={proc.returncode}"
            if proc.real_pid in _lenient_pids(reg):  # type: ignore[attr-defined]
                return
            time.sleep(0.05)
        pytest.fail(f"жертва pid={proc.real_pid} не появилась в реестре {reg} за {timeout} с")

    @staticmethod
    def wait_dead(proc: subprocess.Popen, timeout: float = _KILL_TIMEOUT) -> int:
        """Ждёт смерти через Popen.wait (он же снимает зомби)."""
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pytest.fail(f"процесс pid={proc.pid} не умер за {timeout} с — реап его не убил")


@pytest.fixture(scope="module")
def checkouts(tmp_path_factory) -> dict[str, Path]:
    """Две НАСТОЯЩИЕ копии пакета (не симлинки) — два независимых checkout."""
    base = tmp_path_factory.mktemp("checkouts")
    out: dict[str, Path] = {}
    for name in ("a", "b"):
        root = base / f"checkout_{name}"
        shutil.copytree(
            _PKG_DIR,
            root / "multiprocess_framework",
            symlinks=False,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        out[name] = root
    assert not (out["a"] / "multiprocess_framework").is_symlink()
    return out


@pytest.fixture(scope="module")
def helper_script(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("helper") / "child.py"
    path.write_text(_CHILD_SOURCE, encoding="utf-8")
    return path


@pytest.fixture
def procs():
    """Все запущенные процессы теста: гасятся в finally, что бы ни случилось."""
    spawned: list[subprocess.Popen] = []
    yield spawned
    for p in spawned:
        try:
            if p.poll() is None:
                # Сначала настоящий интерпретатор (потомок лаунчера venv на Windows), пока лаунчер
                # жив и pid потомка не мог быть переиспользован; затем сам Popen.
                real_pid = getattr(p, "real_pid", p.pid)
                if real_pid != p.pid:
                    try:
                        os.kill(real_pid, getattr(signal, "SIGKILL", signal.SIGTERM))
                    except OSError:
                        pass
                p.kill()
            p.wait(timeout=15)
        except Exception:  # noqa: BLE001 — уборка не должна маскировать падение теста
            pass


@pytest.fixture
def make_harness(tmp_path, checkouts, helper_script, procs):
    def factory(name: str = "main") -> Harness:
        return Harness(tmp_path / name, checkouts, helper_script, procs)

    return factory


@pytest.fixture
def h(make_harness) -> Harness:
    return make_harness("main")


# --------------------------------------------------------------------------- C1 / C2


class TestC1PathPerCheckout:
    def test_two_checkouts_get_different_paths_in_same_temp(self, h):
        a, b = h.run("a", "path"), h.run("b", "path")
        # санити: дети правда импортируют СВОЮ копию (иначе тест ни о чём)
        assert a["pkg"].startswith(str(h.checkouts["a"]))
        assert b["pkg"].startswith(str(h.checkouts["b"]))
        assert a["p1"] != b["p1"], "два checkout делят ОДИН реестр — сосед реапнет соседа"
        assert Path(a["p1"]).parent == Path(b["p1"]).parent == h.tmp

    def test_same_checkout_same_path_on_repeated_call(self, h):
        info = h.run("a", "path")
        assert info["p1"] == info["p2"]

    def test_same_checkout_same_path_across_processes(self, h):
        assert h.run("a", "path")["p1"] == h.run("a", "path")["p1"]

    def test_in_process_and_child_agree_for_same_checkout(self, h, monkeypatch):
        """Тот же checkout (само дерево) из процесса теста и из ребёнка с тем же PYTHONPATH."""
        import tempfile

        from multiprocess_framework.modules.process_manager_module.launcher import pid_registry

        for key in ("MULTIPROCESS_PID_FILE", "INSPECTOR_PID_FILE"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MPF_APP_NAME", "AppOne")
        monkeypatch.setattr(tempfile, "tempdir", str(h.tmp))  # кэш gettempdir — единственный вход в temp
        mine = str(pid_registry.pid_file_path())
        child = h.run(_ROOT, "path")
        assert child["pkg"].startswith(str(_ROOT))
        assert child["p1"] == mine


class TestC2FileName:
    @pytest.mark.parametrize("which", ["a", "b"])
    def test_name_starts_with_app_and_ends_with_suffix(self, h, which):
        name = Path(h.run(which, "path")["p1"]).name
        assert name.startswith("AppOne"), name
        assert name.endswith("_system_pids.jsonl"), name


# --------------------------------------------------------------------------- C3 / C4


class TestC3NeighbourSurvives:
    def test_reap_from_other_checkout_keeps_victim_and_file(self, h):
        reg_a = h.reg_path("a")
        victim = h.victim("a")
        assert victim.real_pid in _pids(reg_a)  # type: ignore[attr-defined]
        before = reg_a.read_bytes()

        h.run("b", "reap")

        assert victim.poll() is None, "реап из checkout B убил процесс checkout A"
        assert reg_a.read_bytes() == before, "реап из B изменил реестр checkout A"


class TestC4OwnIsReaped:
    def test_reap_from_same_checkout_kills_victim_and_empties_registry(self, h):
        reg_a = h.reg_path("a")
        victim = h.victim("a")
        assert victim.real_pid in _pids(reg_a)  # type: ignore[attr-defined]

        res = h.run("a", "reap")

        h.wait_dead(victim)
        assert res["killed"] >= 1
        assert _entries(reg_a) == [], "реестр checkout A не пуст после собственного реапа"


# --------------------------------------------------------------------------- C5 / C6 / C6b


def _stale_registry(h: Harness, file_name: str) -> tuple[Path, subprocess.Popen, bytes]:
    """Файл-реестр по имени в temp с записью ЖИВОЙ жертвы (формат register_self: pid + ct)."""
    victim = h.sleeper()
    path = h.tmp / file_name
    ct = psutil.Process(victim.real_pid).create_time()  # type: ignore[attr-defined]
    path.write_text(json.dumps({"pid": victim.real_pid, "ct": ct}) + "\n", encoding="utf-8")  # type: ignore[attr-defined]
    return path, victim, path.read_bytes()


class TestC5UndividedNameIsNotReaped:
    @pytest.mark.parametrize("which", ["a", "b"])
    def test_old_undivided_registry_is_left_alone(self, h, which):
        path, victim, before = _stale_registry(h, "AppOne_system_pids.jsonl")

        h.run(which, "reap", app="AppOne")

        assert victim.poll() is None, "прежний неразделённый реестр реапнут — запись чужого запуска убита"
        assert path.exists(), "прежний неразделённый реестр удалён"
        assert path.read_bytes() == before and before.strip(), "прежний реестр изменён/опустошен"


class TestC6InspectorProductFileIsProtected:
    def test_inspector_app_does_not_reap_unsplit_registry(self, h):
        path, victim, before = _stale_registry(h, "inspector_system_pids.jsonl")

        h.run("a", "reap", app="inspector")

        assert victim.poll() is None, "реестр inspector_system_pids.jsonl реапнут приложением inspector"
        assert path.exists(), "inspector_system_pids.jsonl удалён"
        assert path.read_bytes() == before


class TestC6bLegacyBoundaryPin:
    def test_other_app_still_reaps_and_removes_legacy_product_file(self, h):
        path, victim, _ = _stale_registry(h, "inspector_system_pids.jsonl")

        h.run("a", "reap", app="AppOne")

        h.wait_dead(victim)
        assert not path.exists(), "легаси-реестр inspector остался после реапа другого приложения"


# --------------------------------------------------------------------------- C7


class TestC7LogLines:
    def test_one_line_per_victim_with_pid_and_name_and_total(self, h):
        reg_a = h.reg_path("a")
        v1, v2 = h.victim("a"), h.victim("a")
        dead = _dead_pid()
        with open(reg_a, "a", encoding="utf-8") as f:  # ПОСЛЕДНЯЯ запись — мёртвый pid
            f.write(json.dumps({"pid": dead, "ct": None}) + "\n")
        assert _lenient_pids(reg_a)[-1] == dead
        names = {v.real_pid: psutil.Process(v.real_pid).name() for v in (v1, v2)}  # ДО реапа
        assert all(names.values()), names

        res = h.run("a", "reap")
        lines = res["lines"]

        assert res["killed"] == 2
        for v in (v1, v2):
            mine = [ln for ln in lines if _has_pid(ln, v.real_pid)]
            assert len(mine) == 1, f"pid {v.real_pid}: ожидалась ОДНА строка, получено {len(mine)}: {lines!r}"
            assert names[v.real_pid] in mine[0], f"в строке жертвы нет её имени {names[v.real_pid]!r}: {mine[0]!r}"
        assert not any(_has_pid(ln, dead) for ln in lines), f"в журнале pid мёртвой записи {dead}: {lines!r}"
        assert any(re.search(r"убито\s+2(?!\d)", ln) for ln in lines), f"нет итоговой строки «убито 2»: {lines!r}"
        h.wait_dead(v1)
        h.wait_dead(v2)


# --------------------------------------------------------------------------- C8


class TestC8ExplicitHandles:
    def test_multiprocess_pid_file_beats_default(self, h):
        explicit = str(h.tmp / "explicit.jsonl")
        got = h.run("a", "path", MULTIPROCESS_PID_FILE=explicit)["p1"]
        assert got == explicit

    def test_inspector_pid_file_alone_beats_default(self, h):
        explicit = str(h.tmp / "legacy_handle.jsonl")
        got = h.run("a", "path", INSPECTOR_PID_FILE=explicit)["p1"]
        assert got == explicit

    def test_multiprocess_pid_file_beats_inspector_pid_file(self, h):
        canon, legacy = str(h.tmp / "canon.jsonl"), str(h.tmp / "legacy.jsonl")
        got = h.run("a", "path", MULTIPROCESS_PID_FILE=canon, INSPECTOR_PID_FILE=legacy)["p1"]
        assert got == canon


# --------------------------------------------------------------------------- C9 / C10: одновременный старт


def _wait_for(cond, timeout: float, what: str, procs_to_watch=()):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return
        for p in procs_to_watch:
            if p.poll() is not None and not cond():
                pytest.fail(f"{what}: процесс pid={p.pid} вышел rc={p.returncode} раньше времени")
        time.sleep(0.01)
    pytest.fail(f"{what}: не дождались за {timeout} с")


def _start_together(sync: Path, racers: dict[str, subprocess.Popen]) -> None:
    """Рукопожатие «готов» → общий сигнал «старт»."""
    _wait_for(
        lambda: all((sync / f"{n}.ready").exists() for n in racers),
        60,
        "готовность гонщиков",
        racers.values(),
    )
    (sync / "go").write_text("", encoding="utf-8")


class TestC9SimultaneousStartTwoCheckouts:
    @pytest.mark.timeout(300)
    def test_each_run_reaps_only_own_tail_three_times(self, make_harness):
        for rep in range(3):
            hh = make_harness(f"rep{rep}")
            reg_a, reg_b = hh.reg_path("a"), hh.reg_path("b")
            tail_a, tail_b = hh.victim("a"), hh.victim("b")  # по живому «хвосту» своего checkout

            sync = hh.root / "sync"
            sync.mkdir()
            racers = {"a": hh.spawn("a", "race", str(sync), "a"), "b": hh.spawn("b", "race", str(sync), "b")}
            _start_together(sync, racers)
            _wait_for(
                lambda: all((sync / f"{n}.result").exists() for n in racers),
                90,
                f"повтор {rep}: результаты реапа",
                racers.values(),
            )
            res = {n: json.loads((sync / f"{n}.result").read_text(encoding="utf-8")) for n in racers}

            ctx = f"повтор {rep}"
            assert res["a"]["killed"] == 1, f"{ctx}: реап A вернул {res['a']['killed']}, ожидался 1"
            assert res["b"]["killed"] == 1, f"{ctx}: реап B вернул {res['b']['killed']}, ожидался 1"
            hh.wait_dead(tail_a)
            hh.wait_dead(tail_b)
            # новые записи (register_self гонщиков) живы
            assert racers["a"].poll() is None, f"{ctx}: гонщик A убит"
            assert racers["b"].poll() is None, f"{ctx}: гонщик B убит"
            # в каждом реестре только pid своего checkout; строки — валидный JSON (_pids строгий)
            assert reg_a != reg_b, f"{ctx}: реестры совпали"
            assert set(_pids(reg_a)) == {racers["a"].real_pid}, f"{ctx}: реестр A: {_pids(reg_a)}"  # type: ignore[attr-defined]
            assert set(_pids(reg_b)) == {racers["b"].real_pid}, f"{ctx}: реестр B: {_pids(reg_b)}"  # type: ignore[attr-defined]


class TestC10SimultaneousStartOneCheckout:
    @pytest.mark.timeout(300)
    def test_two_runs_of_same_checkout_keep_registry_consistent(self, h):
        reg_a = h.reg_path("a")
        h.victim("a")  # хвост прошлого запуска своего checkout
        foreign = h.victim("b")  # чужой checkout: его pid в реестре A быть не должно

        sync = h.root / "sync"
        sync.mkdir()
        racers = {"a1": h.spawn("a", "race", str(sync), "a1"), "a2": h.spawn("a", "race", str(sync), "a2")}
        _start_together(sync, racers)
        _wait_for(
            lambda: all((sync / f"{n}.result").exists() or p.poll() is not None for n, p in racers.items()),
            90,
            "завершение обоих запусков",
        )

        for n, p in racers.items():
            assert "Traceback" not in h.stderr_of(p), f"{n}: Traceback в stderr:\n{h.stderr_of(p)}"
            assert p.poll() in (None, 0, -9), f"{n}: неожиданный код возврата {p.poll()}"
        pids = _pids(reg_a)  # строгий разбор: каждая строка — валидный JSON
        assert foreign.real_pid not in pids, "в реестре A оказался pid чужого checkout"  # type: ignore[attr-defined]
