---
name: feedback-coverage-holds-settrace-not-setprofile
description: "coverage.py занимает sys.settrace, а sys.getprofile под --cov пуст: счётчик вызовов на setprofile с покрытием не конфликтует, а ассерт `gettrace() is None` даёт ложный красный"
metadata:
  node_type: memory
  type: feedback
---

Замер на живом прогоне (2026-09-02, слепой тестер, добор Task 2.10): под `pytest --cov`
`sys.gettrace()` занят `coverage.CTracer`, а `sys.getprofile()` — **`None`**.

Два следствия, оба практические:

1. **Инструмент, считающий вызовы через `sys.setprofile`, с покрытием не конфликтует** — каналы
   разные. Это не рассуждение о том, «как обычно бывает», а наблюдение; на нём и стоит выбор
   механизма для общего помощника дорог `_road_cost.count_calls`.
2. **`assert sys.gettrace() is None` в тесте — ложный красный под `make test`**, который в этом
   проекте всегда идёт с покрытием. Сравнивать надо со СНИМКОМ, снятым до вызова, а не с `None`.
   Ошибка поймана до коммита ровно этим замером.

**Why:** «восстанавливает хук» — утверждение о ЧУЖОМ инструменте, и проверять его надо против
того, что реально стоит в прогоне, а не против пустоты. Пустота — состояние голого интерпретатора,
которого в боевом прогоне не бывает.

**How to apply:** любой тест, утверждающий что-то про `settrace`/`setprofile`, берёт базу снимком
`sys.gettrace()`/`sys.getprofile()` перед действием. И: проверить «те же числа под покрытием»
изнутри процесса нельзя — переключение `coverage.py` живёт в скомпилированном расширении, а
вложенный `coverage.Coverage()` рискует срубить настоящие цифры покрытия прогона; честная замена —
поставить свой no-op `settrace` и сравнить с базой, сказав об этом вслух. Родня:
[[feedback_global_clock_patch_flake]], [[feedback_pytest_owns_threading_excepthook_for_the_session]],
[[feedback_tests_invisible_to_testpaths]].
