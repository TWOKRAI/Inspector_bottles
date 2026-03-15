#!/usr/bin/env bash
# Запуск Inspector Prototype с корректным PYTHONPATH.
# Выполнять из каталога Inspector_prototype (родитель этого скрипта).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROTO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MODULES="$PROTO_ROOT/multiprocess_framework/refactored/modules"

export PYTHONPATH="$PROTO_ROOT:$MODULES${PYTHONPATH:+:$PYTHONPATH}"

# Очистка устаревших SharedMemory сегментов от предыдущих запусков (macOS/Linux POSIX shm)
PYTHON_CMD="${PYTHON_CMD:-python3}"
"$PYTHON_CMD" -c "
from multiprocessing import shared_memory
for name in ['camera_frame_0', 'camera_frame_1', 'processor_mask_0', 'processor_mask_1', 'rendered_frame_0', 'rendered_frame_1', 'mask_frame_0', 'mask_frame_1']:
    try:
        shm = shared_memory.SharedMemory(name=name, create=False)
        shm.close()
        shm.unlink()
        print(f'Cleaned up stale shm: {name}')
    except FileNotFoundError:
        pass
" 2>/dev/null || true

exec "$PYTHON_CMD" -m multiprocess_prototype.main "$@"
