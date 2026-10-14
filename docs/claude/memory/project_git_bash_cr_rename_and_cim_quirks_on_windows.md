---
name: project_git_bash_cr_rename_and_cim_quirks_on_windows
description: "Git Bash on Windows: gawk 5.0 strips \\r itself (an awk 'keep \\r' mutant is equivalent), mv over a file Python/.NET holds open fails 'Device or resource busy', $(powershell …) keeps inner \\r, Win32_Processor.LoadPercentage costs ~1 s per query and can be empty (Git Bash: CR, rename busy, пустой замер CIM)"
module: [scripts]
mechanism: [windows-env, dev-tooling]
metadata:
  type: project
---

Measured 2026-10-14 (reviewer, plan review of machine-gate Task 1.2) on Git for Windows bash, GNU Awk 5.0.0,
coreutils 8.32, Windows 10 Pro 19045:

1. gawk reads files and pipes in text mode and strips the trailing `\r`:
   `printf 'coordinator: c1 | since x\r\n' | awk '{print length($0)}'` -> 25; with `-v BINMODE=3` -> 26.
   `while IFS= read -r` keeps it (26). A "do not strip \r" mutant in an awk reader is equivalent on Windows and
   bites only on Linux; predict CR injections per reader (awk vs read).
2. MSYS `mv tmp target` over a target held open by Python `open(..., "rb")` or .NET `[IO.File]::OpenRead` ->
   rc 1 `Device or resource busy`, target unchanged, tmp left behind. A target held by an MSYS reader
   (`exec 3<target`) does not block (rc 0). An "atomic tmp + mv" writer must check mv's rc and remove tmp.
   After a successful mv `os.stat(target).st_ino` changes (NTFS file id) — a cheap test that the file was
   replaced, not rewritten in place. No `flock` in Git Bash; `set -C` (O_EXCL) is the available mutex.
3. `x=$(powershell -NoProfile -Command '12; 34')` -> bytes `12\r\n34`: only the trailing newline goes, the inner
   `\r` stays; `read < <(powershell ...)` keeps `\r` too. Pipe powershell output through `tr -d '\r'`.
4. `(Get-CimInstance Win32_Processor).LoadPercentage` costs ~1 s per query (5 back-to-back: 5.16 s) and
   returned `$null` once in 15 samples; 5 samples with `Start-Sleep 1` between them cost ~10 s per call
   (10.19 s, 9.92 s — two repeats, an observation, not a number), not 5. `Win32_OperatingSystem`: 80–160 ms.

**Why:** a spec saying "5 samples 1 s apart", "strip \r", "atomic mv" read right and was wrong on this
machine in three places; tests built from it would stay green on the broken path.

**How to apply:** for any bash tool on Windows that rewrites a shared file or parses powershell output —
check mv's rc and clean tmp, `tr -d '\r'` the powershell output, skip null CIM samples, and mark a CR
mutant in an awk reader as equivalent on Git Bash. Related: [[feedback_a_hook_dead_on_windows_by_a_trailing_cr]].
