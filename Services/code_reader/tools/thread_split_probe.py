"""Опыт на железе: почему возврат режима камеры (ID3013) отвечает 0x80020206 (MV_CODEREADER_E_NETER).

Порядок вызовов повторяет SdkCodeReader (Services/code_reader/core/sdk_reader.py):
  open -> [для узла: прочитать исходное, записать] -> start_grabbing -> цикл get_frame ->
  stop_grabbing -> возврат узлов в ОБРАТНОМ порядке (set_enum / set_int) -> close.

Режимы потока:
  --mode same  : всё в одном потоке (главном), как делает mvcr_probe.
  --mode split : open + запись + start_grabbing в потоке A (он завершается); цикл, stop_grabbing,
                 возврат, close в потоке B (как в сервисе).
  --delay S    : пауза S секунд между stop_grabbing и первой записью возврата.

Что добавлено к первой версии:
  * после КАЖДОЙ записи (запись режима и возврат) тот же узел перечитывается:
        <ЗАПИСЬ|ВОЗВРАТ> <узел>: записано=<значение> код=<0x...|OK> прочитано=<значение>
    «код=0x80020206, прочитано=исходное» -> SDK соврал об отказе, запись дошла (H5);
    «код=0x80020206, прочитано=записанное прежде» -> запись не дошла.
  * --reopen-after 1,15 : после close подождать N с (от момента close), открыть заново, прочитать
    TriggerMode / TriggerSource / TriggerSelfTriggerPeriod, закрыть.
  * время каждого вызова: мс=
  * в конце сводка: исходное -> после записи -> после возврата (прочитано) -> после повторного открытия.
  * безопасность: исходные читаются и печатаются ДО записи; при любом выходе (в т.ч. Ctrl+C) скрипт
    дописывает возврат и печатает результат; UserSetSave не пишется никогда; без --ip на реальном
    приборе отказ; --seconds по умолчанию 3, максимум 30.

Запуск (из корня репозитория):
  PYTHONUTF8=1 PYTHONPATH=. .venv/Scripts/python.exe <этот файл> --ip 192.168.1.10 --mode split --reopen-after 1,15
  --fake [--fake-nack lie|real|late] : без железа (фейк из Services/code_reader/tests).
"""

import argparse
import sys
import threading
import time
import traceback

from multiprocess_framework.modules.base_manager import open_scope
from Services.code_reader.sdk.errors import SdkError

M, S, P = "TriggerMode", "TriggerSource", "TriggerSelfTriggerPeriod"
ORDER = (M, S, P)  # порядок записи; возврат идёт в обратном
PARENT = {M: None, S: M, P: S}
# узел -> (тип: e=enum, i=int; значение режима). ТОЛЬКО эти три узла разрешено писать (UserSetSave -- никогда).
NODES = {M: ("e", "On"), S: ("e", "SelfTrigger"), P: ("i", 40)}
NETER = 0x80020206
# Бюджет закрытия области потоков: finish() уже ждал каждый поток по done до 30 с, поток, живой после этого,
# завис -- close его только собирает. Итого граница ожидания около 30 с + бюджет (прежний не-daemon поток
# при зависшем вызове SDK держал процесс бесконечно).
_SCOPE_BUDGET_S = 5.0


def code_of(exc: BaseException) -> str:
    if isinstance(exc, SdkError):
        return f"0x{exc.code:08X}"
    return type(exc).__name__


def timed(label, fn, *args):
    """Вызов с замером. Возвращает (результат, код отказа или None). KeyboardInterrupt не глотается."""
    t0 = time.perf_counter()
    res, code, detail = None, None, ""
    try:
        res = fn(*args)
    except Exception as exc:  # noqa: BLE001 -- отказ SDK это данные опыта, не повод падать
        code, detail = code_of(exc), str(exc)
    ms = (time.perf_counter() - t0) * 1000
    status = "OK" if code is None else f"FAIL {code} {detail}"
    print(f"  {label:<46} мс={ms:8.2f}  {status}", flush=True)
    return res, code


def show(value, err) -> str:
    if err is not None:
        return f"ERR {err}"
    return "н/д" if value is None else str(value)


class Probe:
    def __init__(self, api, entry, args):
        self.api, self.entry, self.a = api, entry, args
        self.abort = threading.Event()
        self.h = None
        self.grabbing = False
        self.orig: dict[str, int] = {}
        self.orig_when: dict[str, str] = {}
        self.written: list[str] = []  # узлы, в которые ПЫТАЛИСЬ писать (порядок первой записи)
        self.landed: list[str] = []  # узлы, которые надо возвращать (запись прошла или могла пройти)
        self.last_seen: dict[str, int] = {}  # последнее УСПЕШНО прочитанное значение узла
        self.unreadable: set[str] = set()  # последнее чтение узла отказало
        self.after_apply: dict[str, tuple] = {}
        self.restore_res: dict[str, dict] = {}
        self.reopen: dict[float, dict[str, tuple]] = {}
        self.reopen_actual: dict[float, float] = {}
        self.t_close = None
        self.failed = None
        self.completed = False
        self.threads: list[threading.Event] = []  # done-события потоков
        self.scope = open_scope("code_reader.thread_split_probe", budget_s=_SCOPE_BUDGET_S)
        self.cleanup_note = "не запускался"

    # ------------------------------------------------------------------ примитивы

    def read(self, node, label):
        fn = self.api.get_enum if NODES[node][0] == "e" else self.api.get_int
        r, code = timed(label, fn, self.h, node)
        if code is None:
            self.last_seen[node] = r["cur"]
            self.unreadable.discard(node)
            return r["cur"], None
        self.unreadable.add(node)
        return None, code

    def write(self, prefix, node, value, how):
        """Записать узел и сразу перечитать. how: str (SetEnumValueByString), enum (SetEnumValue), int."""
        if node not in NODES:
            raise RuntimeError(f"запись в узел {node!r} запрещена (разрешены {ORDER})")
        if (NODES[node][0] == "i") != (how == "int"):
            raise RuntimeError(f"способ {how!r} не подходит узлу {node}")
        fn = {"str": self.api.set_enum_str, "enum": self.api.set_enum, "int": self.api.set_int}[how]
        if node not in self.written:
            self.written.append(node)
        self.last_seen.pop(node, None)  # до перечитывания значение узла неизвестно
        self.unreadable.discard(node)
        _, code = timed(f"{prefix}: {fn.__name__} {node}={value}", fn, self.h, node, value)
        back, back_err = self.read(node, f"  читаю обратно {node}")
        print(f"  {prefix} {node}: записано={value} код={code or 'OK'} прочитано={show(back, back_err)}", flush=True)
        return {"value": value, "code": code, "back": back, "back_err": back_err}

    @staticmethod
    def how_restore(node):
        return "int" if NODES[node][0] == "i" else "enum"

    def hand(self) -> str:
        return ", ".join(f"{n}={self.orig[n]}" for n in ORDER if n in self.orig) or "(исходные не прочитаны)"

    # ------------------------------------------------------------------ фазы

    def phase_a(self):
        print(f"[phase_a thread={threading.current_thread().name}]", flush=True)
        h, code = timed("open", self.api.open, self.entry)
        if code is not None:
            raise RuntimeError(f"open: {code}")
        self.h = h
        print("--- исходные значения (ДО любой записи) ---", flush=True)
        for node in ORDER:
            v, code = self.read(node, f"read исходное {node}")
            if code is None:
                self.orig[node], self.orig_when[node] = v, "до записи"
                print(f"ORIG {node} = {v}", flush=True)
            else:
                print(f"ORIG {node}: до записи не читается ({code}); прочитаю перед записью самого узла", flush=True)
        print(f"Если скрипт оборвётся, вручную (IDMVS): {self.hand()}", flush=True)
        print("--- запись режима (порядок сервиса) ---", flush=True)
        for node in ORDER:
            kind, value = NODES[node]
            parent = PARENT[node]
            if parent and parent not in self.landed:
                print(f"SKIP {node}: родитель {parent} не записан (как в сервисе)", flush=True)
                continue
            if node not in self.orig:
                v, code = self.read(node, f"read исходное {node} (перед записью узла)")
                if code is not None:
                    print(f"SKIP {node}: исходное не прочиталось ({code}); без него не пишу", flush=True)
                    continue
                self.orig[node], self.orig_when[node] = v, "перед записью узла"
                print(f"ORIG {node} = {v} (прочитано перед записью узла)", flush=True)
                print(f"Если скрипт оборвётся, вручную (IDMVS): {self.hand()}", flush=True)
            res = self.write("ЗАПИСЬ", node, value, "int" if kind == "i" else "str")
            self.after_apply[node] = (res["back"], res["back_err"])
            if res["code"] is None or res["back"] is None or res["back"] != self.orig[node]:
                self.landed.append(node)  # прошла, либо отказала но значение сменилось/неизвестно: вернуть надо
        _, code = timed("start_grabbing", self.api.start_grabbing, self.h)
        if code is not None:
            raise RuntimeError(f"start_grabbing: {code}")
        self.grabbing = True

    def phase_b(self):
        print(f"[phase_b thread={threading.current_thread().name}]", flush=True)
        start = time.perf_counter()
        end = start + self.a.seconds
        n = 0
        while time.perf_counter() < end and not self.abort.is_set():
            try:
                n += self.api.get_frame(self.h, 250) is not None
            except Exception as exc:  # noqa: BLE001
                print("  get_frame:", code_of(exc), flush=True)
                time.sleep(0.05)
        print(f"  кадров за {time.perf_counter() - start:.1f} с: {n}", flush=True)
        _, code = timed("stop_grabbing", self.api.stop_grabbing, self.h)
        if code is None:
            self.grabbing = False
        if self.a.delay:
            self.abort.wait(self.a.delay)
            print(f"  пауза {self.a.delay:g} с между stop_grabbing и возвратом", flush=True)
        print("--- возврат (обратный порядок, как _restore_trigger) ---", flush=True)
        for node in reversed(self.landed):
            self.restore_res[node] = self.write("ВОЗВРАТ", node, self.orig[node], self.how_restore(node))
        _, code = timed("close", self.api.close, self.h)
        self.h = None  # после close handle непригоден, даже если он отказал (CloseDevice, затем DestroyHandle)
        self.t_close = time.perf_counter()

    def run_thread(self, fn, name):
        # не Thread.join: на Python 3.12.12 после Ctrl+C в join поток казался завершённым при идущем (наблюдено)
        done = threading.Event()

        def target():
            try:
                fn()
            except BaseException as exc:  # noqa: BLE001
                self.failed = f"{name}: {type(exc).__name__}: {exc}"
                print(f"ОШИБКА в потоке {name}:", flush=True)
                traceback.print_exc()
            finally:
                done.set()

        self.threads.append(done)
        self.scope.spawn(lambda _stop: target(), name=name)
        interrupted, deadline = False, None
        while not done.is_set():
            try:
                done.wait(0.2)
            except KeyboardInterrupt:
                if not interrupted:
                    interrupted = True
                    self.abort.set()
                    deadline = time.perf_counter() + 30
                    print("Ctrl+C: цикл остановлен, stop/возврат/close пройдут в потоке штатно", flush=True)
            if deadline is not None and time.perf_counter() > deadline:
                print(f"Поток {name} не завершился за 30 с; дальше без него", flush=True)
                break
        if interrupted:
            raise KeyboardInterrupt

    def run(self):
        if self.a.mode == "same":
            self.phase_a()
            self.phase_b()
        else:
            self.run_thread(self.phase_a, "A-open")
            if self.failed is None:
                self.run_thread(self.phase_b, "B-capture")
        self.completed = self.failed is None

    def reopen_phase(self, delays):
        for d in delays:
            wait = d - (time.perf_counter() - self.t_close)
            if wait > 0:
                time.sleep(wait)
            actual = time.perf_counter() - self.t_close
            self.reopen_actual[d] = actual
            print(f"--- reopen: заказано {d:g} с, фактически {actual:.2f} с после close ---", flush=True)
            res: dict[str, tuple] = {}
            self.reopen[d] = res
            h, code = timed("open (повторный)", self.api.open, self.entry)
            if code is not None:
                res.update({n: (None, f"open {code}") for n in ORDER})
                continue
            self.h = h
            try:
                for node in ORDER:
                    res[node] = self.read(node, f"reopen[{d:g}с] читаю {node}")
                    print(f"  REOPEN[{d:g}с] {node} = {show(*res[node])}", flush=True)
            finally:
                timed("close (после reopen)", self.api.close, h)
                self.h = None

    # ------------------------------------------------------------------ завершение

    def _step(self, fn):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 -- возврат важнее выхода: пробуем остальное
            print(f"  шаг прерван: {type(exc).__name__}: {exc}", flush=True)
            return None

    def cleanup(self):
        def parent_ok(n):
            # Узел нечитаем, а предок прочитан исходным: SDK не отдаёт потомка при исходном родителе
            # (так на фейке; на камере не проверено), значит проверить его нельзя -- не считаем отказом.
            p = PARENT[n]
            if p is None:
                return False
            if p not in self.unreadable and self.last_seen.get(p) == self.orig.get(p):
                return True
            return p in self.unreadable and parent_ok(p)

        need, unverified = [], []
        for n in reversed(self.written):
            if n in self.unreadable:
                (unverified if parent_ok(n) else need).append(n)
            elif self.last_seen.get(n) != self.orig[n]:
                need.append(n)
        self.unverified = unverified
        if self.h is None and not need:
            what = "ничего не записывалось" if not self.written else "записанные узлы читались исходными"
            extra = f"; не проверено (не читаются при исходном родителе): {unverified}" if unverified else ""
            self.cleanup_note = f"не требуется: {what}{extra}"
            return
        print(f"--- ФИНАЛ: проверка/аварийный возврат (thread={threading.current_thread().name}) ---", flush=True)
        if self.h is not None and self.grabbing:
            _, code = self._step(lambda: timed("финал stop_grabbing", self.api.stop_grabbing, self.h)) or (
                None,
                "прервано",
            )
            if code is None:
                self.grabbing = False
        if need and self.h is None:
            r = self._step(lambda: timed("финал open", self.api.open, self.entry))
            if r is None or r[1] is not None:
                self.cleanup_note = f"НЕ УДАЛСЯ: open не вышел; вернуть вручную: {self.hand()}"
                return
            self.h = r[0]
        for node in need:
            self._step(lambda node=node: self.write("АВАРИЙНЫЙ ВОЗВРАТ", node, self.orig[node], self.how_restore(node)))
        if self.h is not None:
            self._step(lambda: timed("финал close", self.api.close, self.h))
            self.h = None
        failed = [n for n in need if self.last_seen.get(n) != self.orig[n]]
        extra = f"; не проверено: {unverified}" if unverified else ""
        if not need:
            self.cleanup_note = f"только закрыл handle{extra}"
        elif failed:
            self.cleanup_note = f"НЕ УДАЛСЯ для {failed}; вернуть вручную: {self.hand()}{extra}"
        else:
            self.cleanup_note = (
                f"выполнен для {need}: теперь читаются исходные (читалось на том же handle, что и запись){extra}"
            )

    def verdict(self, node):
        o, r = self.orig.get(node), self.restore_res.get(node)
        if o is None:
            return "исходное не прочитано, узел не трогали"
        if r is None:
            return "возврат не выполнялся" + ("" if node in self.landed else " (запись в узел не доходила)")
        code, back = r["code"], r["back"]
        if code is None:
            if back == o:
                base = "возврат OK, прочитано исходное"
            elif back is None:
                base = f"код OK, но прочитать не удалось ({r['back_err']})"
            else:
                base = f"КОД OK, НО прочитано {back} != исходное {o}"
        elif back == o:
            base = f"H5: SDK вернул {code}, но прочитано исходное {o} -- запись, вероятно, ДОШЛА"
        elif back is None:
            base = f"запись отказала {code}, прочитать не удалось -- НЕЯСНО"
        else:
            base = f"запись НЕ ДОШЛА: {code}, прочитано {back} != исходное {o}"
        extras = []
        for d in sorted(self.reopen):
            v, err = self.reopen[d].get(node, (None, "н/д"))
            if err is not None or v is None:
                continue
            if v == o and back != o:
                extras.append(f"после reopen {d:g}с исходное -- применилось позже или при close")
            elif v != o and back == o:
                extras.append(f"ВНИМАНИЕ: после reopen {d:g}с НЕ исходное ({v}) -- readback на том же handle обманул")
        return base + ("; " + "; ".join(extras) if extras else "")

    def finish(self):
        for done in self.threads:
            deadline = time.perf_counter() + 30
            while not done.is_set() and time.perf_counter() < deadline:
                try:
                    done.wait(0.2)
                except KeyboardInterrupt:
                    self.abort.set()
        print(f"жду закрытия области потоков до {_SCOPE_BUDGET_S:g} с", flush=True)
        # _step: Ctrl+C, пришедший в ожидании внутри close, не должен пропустить возврат узлов и сводку
        report = self._step(self.scope.close)
        if report is not None and (report.survivors or not report.complete):
            left = ", ".join(report.survivors)
            print(f"Поток зонда не завершился за бюджет {_SCOPE_BUDGET_S:g} с: {left}", flush=True)
        self._step(self.cleanup)
        self.summary()

    def summary(self):
        print("\n=== СВОДКА: исходное -> после записи -> после возврата (прочитано) -> после повторного открытия ===")
        for node in ORDER:
            o = self.orig.get(node, "н/д")
            wr = show(*self.after_apply[node]) if node in self.after_apply else "не писался"
            r = self.restore_res.get(node)
            rs = (
                "не возвращался"
                if r is None
                else show(r["back"], r["back_err"]) + (f" [код {r['code']}]" if r["code"] else "")
            )
            ro = (
                ", ".join(f"{d:g}с={show(*self.reopen[d].get(node, (None, None)))}" for d in sorted(self.reopen))
                or "не заказано"
            )
            print(f"{node:<26}: {o} -> {wr} -> {rs} -> {ro}")
        for node in ORDER:
            print(f"вердикт {node}: {self.verdict(node)}")
        print(f"финальный возврат: {self.cleanup_note}; исходные для руки: {self.hand()}", flush=True)


# ---------------------------------------------------------------------- фейк


def make_fake(nack):
    """FakeNodeApi из тестов + реалистичная доступность узлов и ответ NETER на запись ПОСЛЕ stop_grabbing.

    lie  : значение записано, ответ 0x80020206 (SDK лжёт об отказе).
    real : не записано, ответ 0x80020206.
    late : не записано, ответ 0x80020206, но применяется при close этого handle.
    Свежий handle (после повторного open) пишет нормально.
    """
    from Services.code_reader.sdk.errors import E_GC_ACCESS
    from Services.code_reader.tests.test_sdk_trigger import FakeNodeApi

    class ProbeFake(FakeNodeApi):
        def __init__(self):
            super().__init__()
            self._after_stop = {e.handle: False for e in self.entries}
            self._pending: dict = {}

        def _access(self, h, name, *, write):
            if write and self._grabbing[h]:
                raise SdkError(E_GC_ACCESS, f"MV_CODEREADER_SetValue[{name}]")
            v = self.values[h]
            ok = {M: True, S: v[M] == 1, P: v[M] == 1 and v[S] == 7}[name]
            if not ok:
                raise SdkError(E_GC_ACCESS, f"MV_CODEREADER_Node[{name}]")

        def open(self, entry):
            self._after_stop[entry.handle] = False
            return super().open(entry)

        def stop_grabbing(self, h):
            super().stop_grabbing(h)
            self._after_stop[h] = True

        def close(self, h):
            if nack == "late":
                for name, value in self._pending.pop(h, []):
                    self._store(h, name, value)
            super().close(h)

        def _nack_write(self, h, method, name, value):
            self._enter(h, method, name, value)
            self._access(h, name, write=True)
            if nack == "lie":
                self._store(h, name, value)
            elif nack == "late":
                self._pending.setdefault(h, []).append((name, value))
            raise SdkError(NETER, f"MV_CODEREADER_{method}[{name}]")

        def set_enum(self, h, name, value):
            if nack and self._after_stop[h]:
                return self._nack_write(h, "set_enum", name, value)
            return super().set_enum(h, name, value)

        def set_int(self, h, name, value):
            if nack and self._after_stop[h]:
                return self._nack_write(h, "set_int", name, value)
            return super().set_int(h, name, value)

    return ProbeFake()


# ---------------------------------------------------------------------- main


def seconds_arg(s):
    v = float(s)
    if not 0 <= v <= 30:
        raise argparse.ArgumentTypeError("--seconds должен быть от 0 до 30")
    return v


def delay_arg(s):
    v = float(s)
    if not 0 <= v <= 60:
        raise argparse.ArgumentTypeError("--delay должен быть от 0 до 60")
    return v


def reopen_arg(s):
    try:
        vals = sorted({float(x) for x in s.split(",") if x.strip()})
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"--reopen-after: список секунд через запятую ({exc})") from exc
    if any(not 0 <= v <= 300 for v in vals):
        raise argparse.ArgumentTypeError("--reopen-after: каждое значение от 0 до 300 с")
    return vals


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", help="IP прибора (обязателен на реальном приборе)")
    ap.add_argument("--mode", choices=("same", "split"), default="same")
    ap.add_argument("--delay", type=delay_arg, default=0.0, help="пауза между stop_grabbing и возвратом, с (0..60)")
    ap.add_argument("--seconds", type=seconds_arg, default=3.0, help="длительность захвата, с (0..30, по умолчанию 3)")
    ap.add_argument(
        "--reopen-after", type=reopen_arg, default=[], help="секунды после close через запятую, например 1,15"
    )
    ap.add_argument("--fake", action="store_true")
    ap.add_argument(
        "--fake-nack", choices=("lie", "real", "late"), help="только с --fake: как фейк отвечает на возврат"
    )
    a = ap.parse_args()
    if a.fake_nack and not a.fake:
        ap.error("--fake-nack работает только с --fake")
    if not a.fake and not a.ip:
        print("ОТКАЗ: без --ip скрипт на реальном приборе не работает (чтобы не взять чужой). Укажи --ip.")
        return 2

    if a.fake:
        api = make_fake(a.fake_nack)
        entry = api.entries[0]
    else:
        from Services.code_reader.sdk.api import MvCodeReaderApi

        api = MvCodeReaderApi()
        found = api.enum_devices()
        entry = next((e for e in found if e.ip == a.ip), None)
        if entry is None:
            print(f"прибор {a.ip} не найден; видны: {[e.ip for e in found]}")
            return 1
    print(
        f"ПРИБОР: ip={entry.ip} model={entry.model} serial={entry.serial} mode={a.mode} delay={a.delay:g} "
        f"seconds={a.seconds:g} reopen={a.reopen_after or '-'} fake_nack={a.fake_nack or '-'}",
        flush=True,
    )

    probe = Probe(api, entry, a)
    rc = 0
    try:
        probe.run()
        if probe.failed:
            rc = 1
        elif a.reopen_after and probe.t_close is not None:
            probe.reopen_phase(a.reopen_after)
    except KeyboardInterrupt:
        print("Ctrl+C: выхожу, сначала возврат", flush=True)
        probe.abort.set()
        rc = 130
    except BaseException:  # noqa: BLE001
        traceback.print_exc()
        rc = 1
    finally:
        probe.finish()
    return rc


if __name__ == "__main__":
    sys.exit(main())
