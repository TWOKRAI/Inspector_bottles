# Исследование: Python 3.15/3.16, free-threading, субинтерпретаторы, WASM (состояние на 2026-11-22)

Дата исследования: 2026-11-22. Бюджет: 40 вызовов инструментов, исчерпан. Все ссылки ниже получены через WebFetch или WebSearch в этом прогоне; дата источника указана рядом.
Метки: ready / partial / experimental / not ready. «не нашёл» = не найдено, не угадывалось.

## Сводка

| Тема | Статус | Главное |
|---|---|---|
| Python 3.15 final | ready | вышел 9 Oct 2026 |
| PEP 810 lazy imports | ready | новая фича 3.15, только на уровне модуля |
| JIT в 3.15 | experimental | 7–8% геомедиана на x86-64 Linux (по заявлению whatsnew) |
| Python 3.16 | not ready (план) | beta1 2027-05-04, final 2027-10-05 (ожидаемые даты) |
| free-threaded 3.14t | partial | официально поддерживается, но опционален |
| free-threaded 3.15t | partial | macOS-установщик ставит его по умолчанию; Windows-статус не найден |
| numpy 2.5.5 free-threaded | ready | wheels cp314t и cp315t, включая win_amd64 |
| msgspec 0.22.0 | partial | cp314t есть на Windows, macOS, Linux; cp315t не проверен |
| pydantic-core 2.50.5 | partial | t-wheels есть; платформы не проверены |
| torch 2.15.0 | partial | cp314t на win_amd64, macOS arm64, Linux; cp313t нет |
| onnxruntime 1.32.0 | not ready (Windows) | cp313t/cp314t только Linux |
| opencv-python 5.1.0.95 | not ready | t-wheels не найдены |
| PySide6 6.12.0 | not ready | все wheels cp310-abi3, t-wheels нет |
| concurrent.interpreters | ready (с оговорками) | Python 3.14+, не WASI |
| numpy в субинтерпретаторах | не нашёл (текущий статус) | официально не заявлено |
| WASI 0.3 (спецификация) | ready | ратифицирован 2026-06-11 |
| componentize-py (Python-гость) | experimental | async для Python «в работе» |
| numpy/OpenCV в WASM-компоненте | not ready / не нашёл | нет подтверждения |
| камера из WASM | не нашёл | proposal не найден |
| wasi-gfx / wasi:webgpu | experimental (Phase 2) | windowing вне scope |
| wasi-nn | experimental (Phase 2) | инференс-API, обновлений 2026 не найдено |

## 1. Python 3.15 и 3.16

- **Релиз 3.15.** Документация 3.15 говорит «Python 3.15 was released on 9 October 2026» (страница версии 3.15.2; дата источника: актуальна на 2026-11-22). [docs.python.org/3/whatsnew/3.15.html](https://docs.python.org/3/whatsnew/3.15.html). Статус: ready.
- **PEP 810, lazy imports.** Явный soft keyword `lazy`; модуль загружается при первом использовании; режимы `-X lazy_imports` / `PYTHON_LAZY_IMPORTS` (`all` или `normal`, по умолчанию `normal`); разрешено только на уровне модуля. Источник: тот же whatsnew 3.15. Статус: ready (новая фича; для нашего кода полезна только для ускорения старта, влияние на runtime не измерял).
- **PEP 803, abi3t.** C-расширения могут целиться в `abi3t` для совместимости с free-threaded сборками; обычно требует «non-trivial changes»; иначе остаются `abi3` и `cp315t`. Источник: whatsnew 3.15. Статус: partial (нужно, чтобы каждый пакет сам перешёл).
- **JIT.** «The experimental JIT compiler has been significantly upgraded». Заявлено: геомедиана 7–8% над интерпретатором на x86-64 Linux; 11–12% на AArch64 macOS относительно tail-calling интерпретатора; относительно сборки без JIT от −15% до +100% (кроме `unpack_sequence`). Windows в разделе JIT не упомянут (кроме трассировки). Источник: whatsnew 3.15 (раздел Optimizations). Статус: experimental. Для Windows-приложения: не проверено.
- **Free-threading в 3.15.** Официальные macOS-установщики ставят free-threaded поддержку по умолчанию. Официальные Windows 64-bit сборки используют tail-calling interpreter. Источник: whatsnew 3.15 (Release changes). Цифр однопоточного overhead для 3.15t в доступной части страницы не нашёл. mimalloc стал аллокатором по умолчанию для raw-памяти, в том числе на free-threaded сборках (whatsnew 3.15).
- **Прочее из 3.15 (только из сниппета поиска, не открывал полностью):** PEP 686 (UTF-8 по умолчанию), PEP 814 (frozendict), PEP 799 (пакет профилирования). Статус: не проверено.
- **Python 3.16.** PEP 826 (статус Active, создан 2026-02-23): beta 1 — 2027-05-04, rc1 — 2027-07-27, final — 2027-10-05 (все «expected»). В PEP не перечислено ни одной фичи 3.16; JIT и free-threading там не упомянуты. Источник: [peps.python.org/pep-0826](https://peps.python.org/pep-0826/). По сниппету поиска: 3.16.0a2 вышла 2026-11-10; draft What's New содержит regex set operations (не открывал). Статус 3.16: not ready (план; фичи меняются до rc1).

## 2. Free-threaded Python (3.14t / 3.15t)

- **Официальный статус.** PEP 779 — Final, resolution 2025-06-16, Python-Version 3.14. Phase II: free-threaded «officially supported», но опционален. Переход к фазе III (сборка по умолчанию) в PEP не запланирован, отложен на будущий PEP. Источник: [peps.python.org/pep-0779](https://peps.python.org/pep-0779/) (last modified 2025-10-06). Статус: partial.
- **Что написано в 3.14 whatsnew.** Пункт «PEP 779: Free-threaded Python is officially supported»; однопоточный штраф «roughly 5-10%, depending on the platform and C compiler». Источник: [docs.python.org/3/whatsnew/3.14.html](https://docs.python.org/3/whatsnew/3.14.html) (дата источника: релиз 3.14, 2025).
- **Однопоточный overhead — цифры расходятся.** (а) PEP 779: «around 10% (except on macOS, where it's more like 3%)», целевой лимит фазы II — 15%. (б) Howto: «from about 1% on macOS aarch64 to 8% on x86-64 Linux» (pyperformance, без версии). Источник: [docs.python.org/3/howto/free-threading-python.html](https://docs.python.org/3/howto/free-threading-python.html) (страница с отметкой «Last updated on Nov 22, 2026», но версия цифр не указана). Для 3.15t отдельных цифр не нашёл.
- **Предупреждение из howto:** пакеты с C-расширением, не помеченные как готовые, могут включить GIL при импорте, с предупреждением.
- **Трекер py-free-threading.** [py-free-threading.github.io/tracking](https://py-free-threading.github.io/tracking). Колонки CI и PyPI в извлечённом тексте пусты; первая версия с поддержкой указана для numpy 2.1.0, PySide6 6.12.0, PyTorch 2.6.0, pydantic-core 2.29.0, msgspec 0.20.0. OpenCV и onnxruntime в таблице без версии. Даты на странице двусмысленные («September 25, 2026» и «July 10, 2024»). Трекер расходится с PyPI по PySide6 и pydantic-core (см. ниже), поэтому я опираюсь на PyPI.

Проверка wheels по PyPI JSON (загружено 2026-11-22; разбор файлов выполнен малой моделью, см. «открытое»):

| Пакет (версия, дата upload) | cp313t | cp314t | cp315t | Вердикт |
|---|---|---|---|---|
| numpy 2.5.5 (2026-11-15) | — | 10 wheels: macOS, manylinux, musllinux, Windows (win32, amd64, arm64) | 11 wheels, те же платформы | ready. [pypi.org/pypi/numpy/2.5.5/json](https://pypi.org/pypi/numpy/2.5.5/json) |
| pydantic-core 2.50.5 (2026-11-19) | есть | есть | есть (по таблице файлов) | partial: платформы не разбирал. [pypi.org/project/pydantic-core](https://pypi.org/project/pydantic-core/) |
| msgspec 0.22.0 (2026-09-29) | нет | 10 wheels: macOS x2, Linux x6 (вкл. riscv64), Windows x2 | не проверен | partial. [pypi.org/pypi/msgspec/0.22.0/json](https://pypi.org/pypi/msgspec/0.22.0/json) |
| torch 2.15.0 (2026-10-28) | нет | 4 wheels: macOS arm64, Linux aarch64, Linux x86_64, win_amd64 | не проверен | partial. [pypi.org/pypi/torch/2.15.0/json](https://pypi.org/pypi/torch/2.15.0/json) |
| onnxruntime 1.32.0 (2026-11-13) | 4 wheels, только Linux x86_64/aarch64 | то же | не видно | not ready для Windows (нет win/macOS t-wheels). [pypi.org/pypi/onnxruntime/1.32.0/json](https://pypi.org/pypi/onnxruntime/1.32.0/json) |
| opencv-python 5.1.0.95 (2026-11-17) | нет | нет (все wheels abi3) | нет | not ready. [pypi.org/pypi/opencv-python/5.1.0.95/json](https://pypi.org/pypi/opencv-python/5.1.0.95/json) |
| PySide6 6.12.0 (2026-10-08 по странице; дата 6.11.3 позже) | нет | нет (5 wheels, все cp310-abi3) | нет | not ready. [pypi.org/project/PySide6](https://pypi.org/project/PySide6/), [pypi.org/pypi/PySide6/6.12.0/json](https://pypi.org/pypi/PySide6/6.12.0/json) |

- **Qt for Python.** Документация [doc.qt.io/qtforpython-6/](https://doc.qt.io/qtforpython-6/) (страница без версии в извлечении) упоминаний free-threaded не содержит. По сниппету поиска, dev-notes Qt for Python (ноябрь 2026) называют free-threaded патчи «still in development» (не открывал). Статус: not ready.
- **Ограничение метода:** таблицы wheels извлекала малая модель из JSON; spot-check на PyPI не делал. Вердикт по платформам — требует проверки перед решением.

## 3. Субинтерпретаторы

- **concurrent.interpreters.** Добавлен в 3.14. «Not all PyPI packages support use in multiple interpreters yet». Интерпретаторы не делят GIL (с 3.12). Не работает на WASI. Источник: [docs.python.org/3/library/concurrent.interpreters.html](https://docs.python.org/3/library/concurrent.interpreters.html) (дата источника: релиз 3.14 / текущая документация). Статус: ready для чистого Python.
- **Ограничения из той же документации.** Объекты по умолчанию копируются через pickle; разделяемая изменяемость только у `memoryview` и `Queue`; `NotShareableError` для неотправляемых объектов; «do not use multiple interpreters in security-sensitive situations»; изоляция «relatively incomplete until version 3.12»; расширения «may easily violate that» изоляцию; данные, разделённые между интерпретаторами, теряют потокобезопасность GIL.
- **InterpreterPoolExecutor.** В той же странице упомянут только в «See also» («Combines threads with interpreters…»); подробностей и доступности не нашёл.
- **numpy в субинтерпретаторах.** В документации CPython numpy не упомянут. Актуального заявления NumPy не нашёл. Старые данные (только сниппеты поиска, не открывал): в 2019 мейнтейнер писал, что субинтерпретаторы не поддерживаемая конфигурация; в 2022 в рассылке — «not on the NumPy roadmap». Статус: не нашёл (не подтверждено). Вывод: считать numpy в субинтерпретаторах непроверенным, пока не проверен на реальном стенде.
- **Прочие блокеры** (OpenCV, onnxruntime, PySide6 в субинтерпретаторах) — не проверял. Статус: не нашёл.

## 4. WebAssembly

- **WASI 0.3.** Ратифицирован и выпущен 2026-06-11; 0.3.1 — 2026-08-11. Новые примитивы в Component Model: `async func`, `stream<T>`, `future<T>`; `wasi:io` удалён (нет версии 0.3). Патчи 0.3.x каждые ~2 месяца; дата 1.0 не указана. Источники: [wasi.dev/releases/wasi-p3](https://wasi.dev/releases/wasi-p3) (дата: 0.3.1 — 2026-08-11), [bytecodealliance.org/articles/WASI-0.3](https://bytecodealliance.org/articles/WASI-0.3) (дата публикации 2026-06-11). Статус спецификации: ready.
- **Runtimes.** Wasmtime 46+ реализует 0.3.0 и включает по умолчанию (wasi.dev); Wasmtime 43–45 — снапшоты rc, нужны флаги `-Sp3 -W component-model-async=y`. jco поддерживает 0.3 целиком (bytecodealliance, 2026-06). Дату релиза Wasmtime 46 не проверил. Статус: ready (спека и runtime), partial (toolchain).
- **componentize-py.** Последняя версия по PyPI — 0.25.1, 2026-09-12. На странице не указана целевая версия WASI; ограничение: «the application can only import dependencies during build time» (issue #23). [pypi.org/project/componentize-py](https://pypi.org/project/componentize-py/). В bytecodealliance (2026-06): async-поддержка для Python-биндингов «still in progress», сроков нет. Статус: experimental.
- **numpy / OpenCV в WASM-компоненте.** Не нашёл подтверждения, что numpy или OpenCV собираются и работают в WASI-компоненте. Из CPython WASI-документации (сниппеты, не открывал): у CPython WASI-сборка без threading. Статус: not ready / не нашёл.
- **Нативная камера и GPU.** Proposal для камеры не нашёл. Из сниппетов: wasi-i2c, wasi-usb существуют как proposals (не открывал). Статус камеры: не нашёл.
- **wasi-gfx / wasi:webgpu.** Репозиторий WebAssembly/wasi-gfx (страница, которую вернул fetch, описывала wasi:webgpu): «currently in Phase 2»; «Displaying to a screen / windowing API — out of scope». Surface и frame-buffer статус, и депрекация wasi:graphics-context — не проверено (сниппет). [github.com/WebAssembly/wasi-gfx](https://github.com/WebAssembly/wasi-gfx). Статус: experimental (Phase 2).
- **wasi-nn.** Phase 2 (нужны две независимые реализации для Phase 4); API для инференса, backends (TF, ONNX, OpenVINO), graphs как непрозрачные байты. Обновлений 2026 и дат последнего коммита не нашёл. [github.com/WebAssembly/wasi-nn](https://github.com/WebAssembly/wasi-nn). Статус: experimental.
- **Вывод по sandbox для плагинов (моя оценка, не факт из источников).** Модель «WIT-интерфейс плюс чистый Python-плагин» технически возможна через WASI 0.3 и componentize-py, но статус async у Python-гостей незрелый, импорт зависимостей только на этапе сборки, а numpy, OpenCV, камера и GPU из WASM не подтверждены. Для плагинов с numpy/OpenCV/камерой реалистичного пути в 2026 я не вижу; для изоляции данных, которым нужен только bytes/dict, возможно как эксперимент.

## Что я оставил открытым или ненадёжным

- **Бюджет исчерпан** (40 вызовов). Не проверены: JIT на Windows; 3.15t однопоточный overhead; статус Wasmtime 46 по дате; wasi:graphics-context; wasi-camera; numpy/OpenCV/ONNX в WASM; InterpreterPoolExecutor подробно; cp315t для msgspec, torch, onnxruntime (есть только cp313t/cp314t у onnxruntime).
- **Таблицы wheels** разобраны малой моделью из JSON PyPI; spot-check не делал. Вердикт по платформам (особенно pydantic-core и torch на Windows) — требует проверки `pip download --only-binary` или страницы файлов перед решением.
- **Противоречия:** трекер py-free-threading указывает PySide6 6.12.0 и pydantic-core 2.29.0 как поддерживаемые, PyPI не показывает t-wheels у PySide6 6.12.0. Дата PySide6 6.12.0 на странице (2026-10-08) и дата 6.11.3 (2026-10-26) противоречат друг другу. Не разрешил.
- **Дата 3.15:** в whatsnew 9 Oct 2026; сторонний блог давал 1 Oct. Официальную дату беру из whatsnew.
- **Сниппеты поиска без открытия страниц** (не в списке источников, факты не использованы как основа вердикта): фичи 3.15 (UTF-8, frozendict, PEP 799), 3.16 alpha и draft What's New, PySide dev-notes, numpy-рассылка 2019/2022, CPython WASI README, wasi-nn/wasi-gfx сроки.
- **Открыто и вне задачи:** дата 1.0 Component Model не указана; стоит ли пересматривать план плагинов после 3.16 — решение владельца, не исследование.
- **Нет вывода о том, что сейчас работает в проекте:** исследование не проверяло код и не запускало ничего локально.

## Источники (загружены в этом прогоне)

1. https://docs.python.org/3/whatsnew/3.15.html — дата источника: релиз 9 Oct 2026
2. https://docs.python.org/3/whatsnew/3.14.html — дата: релиз 3.14 (2025)
3. https://docs.python.org/3/howto/free-threading-python.html — страница с отметкой 22 Nov 2026
4. https://docs.python.org/3/library/concurrent.interpreters.html — дата: текущая документация
5. https://peps.python.org/pep-0779/ — last modified 2025-10-06
6. https://peps.python.org/pep-0826/ — created 2026-02-23
7. https://py-free-threading.github.io/tracking — даты неоднозначны (Sep 25 2026 / Jul 10 2024)
8. https://pypi.org/project/PySide6/ — 6.12.0 (Oct 2026)
9. https://pypi.org/pypi/PySide6/6.12.0/json — дата 6.12.0 (Oct 2026)
10. https://pypi.org/project/opencv-python/ — 5.1.0.95, 2026-11-17
11. https://pypi.org/pypi/opencv-python/5.1.0.95/json — 2026-11-17
12. https://pypi.org/project/onnxruntime/ — 1.32.0, 2026-11-13
13. https://pypi.org/pypi/onnxruntime/1.32.0/json — 2026-11-13
14. https://pypi.org/pypi/numpy/2.5.5/json — 2026-11-15
15. https://pypi.org/pypi/msgspec/0.22.0/json — 2026-09-29
16. https://pypi.org/pypi/torch/2.15.0/json — 2026-10-28
17. https://pypi.org/project/pydantic-core/ — 2.50.5, 2026-11-19
18. https://doc.qt.io/qtforpython-6/ — версия не извлечена
19. https://wasi.dev/releases/wasi-p3 — 0.3.1 2026-08-11
20. https://bytecodealliance.org/articles/WASI-0.3 — 2026-06-11
21. https://pypi.org/project/componentize-py/ — 0.25.1, 2026-09-12
22. https://github.com/WebAssembly/wasi-gfx — страница (содержание wasi:webgpu), дата не указана
23. https://github.com/WebAssembly/wasi-nn — дата не указана
