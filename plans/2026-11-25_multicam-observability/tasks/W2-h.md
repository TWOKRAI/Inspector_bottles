# Task W2-h: рецепт `hikvision_id3013_quad` — полный и явный контракт камер

- **Статус:** [PENDING] · **Level:** Middle · **Assignee:** developer
- **Module contract:** n/a (рецепт prototype и пин-тест)
- **Dependencies:** W2-a (поля `reconnect`, `link_silence_s`, `reconnect_interval_s`), W2-b (те же у считывателя), W2-g (`device_host_ip`); строки `readiness` — только после решения Р-W2-1; `packet_*` — только после стенда (лестница, шаг 4)
- **Gate:** `machine_gate.sh light <session>` по файлам TESTS
- **Files:** `multiprocess_prototype/recipes/hikvision_id3013_quad.yaml`, `multiprocess_prototype/tests/test_recipe_quad_camera_contract.py`
- **Acceptance:** блок ACCEPTANCE
- **Handoff:** developer (REDS в брифе, красный прогон до правки) -> reviewer (стадия 5, sonnet)

Решение владельца 4 («сделай как лучше и правильнее»), выбор лида: вариант A (явные поля) + вариант C (ожидаемая карта ПК, W2-g). Вариант B (живые правки сами пишутся в рецепт) отвергнут как автоматический: рецепт молча уплывает от того, что утвердили; сохранение живых значений — явное действие администратора с аудитом (после решений по доступу, Р-W2-5). Факты (Explore-карта, `mco-plan2`): у `camera_0` нет `gain` (`quad.yaml:163` — только у `camera_1`), `gain_auto`/`exposure_auto`/`packet_*` не заданы ни у одной камеры; при открытии всё равно пишутся `ExposureAuto Off`, `GainAuto Off`, `Gain 0.0` (умолчания регистра, `params.py:61-72`) — рецепт сегодня не говорит того, что делает прибор.

TASK: W2-h — каждый узел, который пишется в камеру при открытии, задан в рецепте явно; переподключение и карта ПК — тоже   PLAN: plans/2026-11-25_multicam-observability/plan.md
ROLE: developer
CHAIN: lead -> you -> reviewer (стадия 5)

DESIGN (decided by the lead — you type it, you do not derive it):
  1. Конфиг плагина `camera_0`: `gain_auto: "Off"`, `gain: 0.0`, `exposure_auto: "Off"`; `camera_1`: `gain_auto: "Off"`, `exposure_auto: "Off"` (`gain: 23.0` уже есть). Комментарии `quad.yaml:54,129,162,164` о «не задан» — заменить одной строкой «записывается при каждом открытии».
  2. Обе камеры: `reconnect: true`, `link_silence_s: 3.0`, `reconnect_interval_s: 2.0`, `device_host_ip: "192.168.1.100"` (адрес карты ПК стенда 2026-11-25 после удаления второго IPv4). Считыватели `reader_1`, `reader_2`: `reconnect: true`, `link_silence_s: 3.0`, `reconnect_interval_s: 2.0`.
  3. НЕ в этой задаче до решений: `readiness: {hold_s: …}` (Р-W2-1); `packet_managed`/`packet_size`/`packet_delay` (значения прибора не прочитаны: при `packet_managed false` драйвер их не читает).
  4. Пин-тест: грузит рецепт тем же путём, что загрузчик (урок: тест рецепта обязан звать ту же проверку, что launcher — `SystemBlueprint.check`), и сверяет литералы п.1-2 по процессам.

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. multiprocess_prototype/recipes/hikvision_id3013_quad.yaml — п.1-2
  2. multiprocess_prototype/tests/test_recipe_quad_camera_contract.py — новый пин-тест

REDS (predicted red tests):
  - multiprocess_prototype/tests/test_recipe_quad_camera_contract.py::test_cameras_declare_every_node_written_at_open
  - multiprocess_prototype/tests/test_recipe_quad_camera_contract.py::test_sources_declare_reconnect_policy
  - multiprocess_prototype/tests/test_recipe_quad_camera_contract.py::test_cameras_declare_expected_host_ip
  - multiprocess_prototype/tests/test_recipe_quad_camera_contract.py::test_recipe_passes_launcher_check (охранный: зелёный до и после)

ACCEPTANCE (every number with its command):
  - `<py> -m pytest -q --tb=short multiprocess_prototype/tests/test_recipe_quad_camera_contract.py` -> exit 0
  - тесты рецептов prototype (`git grep -l "hikvision_id3013_quad" -- multiprocess_prototype/tests`) -> exit 0

TESTS: bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light <session> <py> -m pytest -q --tb=short multiprocess_prototype/tests/test_recipe_quad_camera_contract.py

OUT OF SCOPE: другие рецепты (`hikvision_dual`, `quad_hw`) — после стенда; сохранение живых значений в рецепт (Р-W2-5, Р-W2-11).
TRAPS: сохранение настроек из GUI стирает комментарии yaml (ADR-PMM-052 п.3) — комментарии не носители правил. Каталог пин-теста: если `multiprocess_prototype/tests/` не тот каталог, где лежат тесты рецептов, — стоп и вопрос лиду (не создавать новый каталог).
HANDOFF IN: W2-a, W2-b, W2-g — имена полей.
REPORT: STATUS (DONE|BLOCKED), files, команды и вывод по ACCEPTANCE, красные до/после, раздел «Что оставил открытым / ненадёжно».
