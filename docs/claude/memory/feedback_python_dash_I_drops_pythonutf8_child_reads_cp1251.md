---
name: feedback-python-dash-I-drops-pythonutf8-child-reads-cp1251
description: "`python -I` отбрасывает PYTHONUTF8: потомок на Windows читает файлы в cp1251 и падает на кириллице; тест чистого процесса даёт `-X utf8` явно (isolated mode, UnicodeDecodeError, кодировка)"
module: [data_schema_module]
mechanism: [windows-env, test-infra]
metadata:
  type: feedback
---

**Замер 2026-11-23, полоса Т (Windows, Python 3.12.12).** `test_logger_seam_no_direct_logger_import.py` запускал
`[sys.executable, "-I", "-c", probe, root]` и падал на чтении русского файла: `-I` игнорирует `PYTHON*` из окружения,
в том числе `PYTHONUTF8=1`, которым гоняют весь прогон. Потомок открывал файл в cp1251. Правка: `"-X", "utf8", "-I"` —
флаг командной строки изоляция не отбрасывает. Красный 3 из 3 до правки, зелёный после.

**Why:** окружение прогона зелёное, а «чистый» дочерний процесс его не видит; симптом похож на битый файл, а не на
кодировку.

**How to apply:** тест, что запускает потомка через `python -I`, `-E` или `-S`, передаёт кодировку флагом `-X utf8`,
а не переменной. Рядом: [[feedback_ru_output_encoding_and_wc]].
