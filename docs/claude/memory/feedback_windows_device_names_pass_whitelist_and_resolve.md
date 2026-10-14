---
name: windows-device-names-pass-whitelist-and-resolve
description: "Windows device names «con .x», «com¹», «lpt²» pass a \\w whitelist and Path.resolve() on Python 3.12; reading con.yaml blocks forever; COM7 is a real port / имена устройств Windows проходят белый список и resolve(), чтение con блокирует"
module: [services/robot_comm]
mechanism: [windows-env, test-assertions]
role: reviewer
metadata:
  type: feedback
---

On Windows 10 with Python 3.12, `Path(dir) / "con .x.yaml"`, `"com¹.yaml"`, `"lpt².yaml"` and `"nul.txt.yaml"`
all resolve to DOS devices: `nt._getfullpathname` returns `\\.\con`, `\\.\com¹`, `\\.\lpt²`, `\\.\nul`.
`Path.resolve()` returns an ordinary path for all of them, so a `resolve().parent == expected` check does not
catch them. A recipe-style whitelist `\w(?:[\w.\- ]*\w)?` accepts them: `\w` matches superscript digits, and
inner spaces are allowed. `ntpath.isreserved` exists only from 3.13.
Measured (T5.2 stage-0 review, 2026-10-14): `Path.read_bytes()` on `programs/con.yaml` and `con .x.yaml` did not
return within 4 s (child process killed). `NUL` reads give `b""` at once. `com¹` gives `FileNotFoundError`.
`HARDWARE\DEVICEMAP\SERIALCOMM` on the owner's machine lists `COM7` and `COM10`, so a program name `com7` opens a real stand port.

**Why:** the T5.2 brief (robot data store) checked only "the part before the first dot" against `con..lpt9`. That missed the
trailing space and the superscript digits. Its first acceptance draft also used `con` as a program name in tests. Under an
injection that removes the check, that test would hang the shared machine.

**How to apply:** the reserved check is `name.partition(".")[0].rstrip(" ").lower() in {"con","prn","aux","nul"} |
{p + c for p in ("com","lpt") for c in "123456789¹²³"}`. Never rely on `resolve()` for devices. Verify a candidate
name with `nt._getfullpathname` (a `\\.\` prefix means a device), never by opening it.
In tests, use the `nul` variants (`nul`, `NUL`, `nul.txt`, `nul .x`) and `com¹`/`lpt³`. Never use `con`/`prn`/`aux`/`com1..9`/`lpt1..9`
as a file name. `con` is safe only as a middle path component (a directory name).
