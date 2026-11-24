# T2 (FramePump): предсказания инъекций лида, записаны ДО написания кода и ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t2-dev` (ветка feat/gfp-t2-frame-pump, база bc82d9363 + код T1). Модуль: `multiprocess_framework/modules/frontend_module/bridge/frame_pump.py`. Тесты: `multiprocess_framework/modules/frontend_module/tests/test_frame_pump.py` (REDS из T2.md: 10 имён; плюс тесты поправки лида — потокобезопасность `stats()` и окно `window_max_age_ms` — вне REDS; плюс hazard-тест автора, если developer его добавит). Слепого tester-а у T2 нет (решение лида при условии пп.4-6 брифа), поэтому набор один; правило «оба набора» не применимо — стадия 5 повторяет те же мутации.

Исполнитель — developer T2 (владелец файлов): временная правка с откатом по sha256 от байтовой копии, файлы гонять по одному через `machine_gate.sh light inspector-bottles-K`. Красный набор (минимум) ОБЯЗАН упасть; красные вне набора — «шире»; тест из набора, оставшийся зелёным, — находка. Имена тестов поправки лида developer назовёт сам; в таблице они обозначены ролью [П-а] (потокобезопасность stats) и [П-б] (окно возраста).

| № | мутация | красный набор (минимум) | примечание |
|---|---|---|---|
| F1 | sink вызывается прямо из put (вызов из потока источника) | test_rate_capped_by_fps_limit; test_sink_runs_in_qt_thread; test_pump_delivers_only_latest_after_blocked_loop; test_sink_exception_does_not_stop_pump; test_stop_no_calls_after; test_slow_key_not_starved_by_fast_key | test_put_posts_no_qt_event ЗЕЛЁНЫЙ (снято стадией 0) |
| F2 | один таймер на все ключи, честный круг по ключам | test_per_key_rates_differ | остальные зелёные |
| F3 | Qt.CoarseTimer вместо PreciseTimer | test_rate_capped_by_fps_limit (30 Гц за 2 с: 42 вместо 52..62); test_per_key_rates_differ; test_unconfigured_key_found_by_scan_and_served | тест 20 Гц за 1 с (14..22) зелёный |
| F4 | период int() вместо ceil() | test_zero_fps_limit_capped_at_60 | остальные зелёные |
| F5 | put шлёт Signal без кадра (будит насос) | test_put_posts_no_qt_event | остальные зелёные; это сторож записи «ни одного Signal с кадром» |
| F6 | sink вызывается при пустом take | test_pump_delivers_only_latest_after_blocked_loop; test_sink_exception_does_not_stop_pump; test_slow_key_not_starved_by_fast_key | |
| F7 | исключение sink останавливает таймер ключа | test_sink_exception_does_not_stop_pump | |
| F8 | stop() не гасит таймеры | test_stop_no_calls_after | возможное заражение соседних тестов — зафиксировать |
| F9 | скан находит ключ, но таймер не заводит | test_unconfigured_key_found_by_scan_and_served | |
| F10 | stats() и обновление счётчиков без общего замка (замок снят в stats и set_keys) | [П-а]: потоковый тест читателя stats() при setswitchinterval(1e-6) и 200 вызовах set_keys: красный (RuntimeError или рваный снимок) | зелёный на стандартном интервале допустим: проверяется только при 1e-6; сообщить, сколько прогонов из N красные |
| F11 | stats() без аргумента сбрасывает окно window_max_age_ms | [П-б] | остальные зелёные |
| F12 | stats(reset_window=True) окно не сбрасывает | [П-б] | |
| F13 | window_max_age_ms считается из накопленного max_age_ms (одно значение) | [П-б] | |
| F14 | stats() отдаёт живой внутренний словарь, а не копию | [П-а] или отдельный тест изменяемости снимка; если такого теста нет — находка (дыра покрытия) | |

Критерий находки: (a) тест из красного набора остался зелёным; (b) sha256 после отката не совпал; (c) F1: test_put_posts_no_qt_event стал красным — расхождение (значит, у put есть путь в Qt); (d) F14: ни один тест не красный — дыра покрытия, developer добавляет тест.
Условие прогона: Qt-тесты offscreen; допуски частот брать из ACCEPTANCE брифа, не расширять под мутантов. Часы под загрузкой: красный набор частотных тестов проверять 2 прогона на каждую мутацию (частотные допуски — по замерам reviewer-а на свободной машине).
