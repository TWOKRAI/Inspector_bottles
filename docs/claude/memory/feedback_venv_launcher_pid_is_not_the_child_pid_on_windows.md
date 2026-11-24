---
name: feedback-venv-launcher-pid-is-not-the-child-pid-on-windows
description: "Venv-лаунчер python.exe на Windows запускает настоящий интерпретатор потомком: Popen.pid — pid лаунчера; тест на реестр pid / kill по pid врёт (launcher, venv, pid_registry, taskkill)"
module: [process_manager_module]
mechanism: [windows-env, test-infra]
metadata:
  type: feedback
---

**Замер 2026-11-23, полоса Т.** `test_pid_registry_checkout_acceptance.py`: `Popen([venv/python.exe, ...]).pid` не равен
pid процесса, что пишет `os.getpid()` в потомке: лаунчер venv держит свой pid, интерпретатор — дочерний. Реестр
видел настоящий pid, тест сверял с лаунчерным → красный; `os.kill` по лаунчерному pid не гасит потомка.
Правка: потомок пишет `os.getpid()` в файл, тест ждёт его и держит `proc.real_pid`; гасит `os.kill(real_pid)`.

**Why:** на Linux и macOS `Popen.pid` и есть процесс интерпретатора, поэтому дефект платформозависимый.

**How to apply:** любой тест, что сверяет pid потомка из `sys.executable` venv или убивает его, берёт pid изнутри
потомка. Не заключать «процесс не найден» без этой проверки.
