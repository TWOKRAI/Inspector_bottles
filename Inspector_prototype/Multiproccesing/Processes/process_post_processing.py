"""
Пост-обработка: модульный пайплайн (области + цепочки).

Этап 1: Вырез областей (прямоугольники) на изображении
Этап 2: Для каждой области — своя цепочка обработчиков
Этап 3: Объединение результатов, отображение по view_mode
"""

import time
import numpy as np
from queue import Empty
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../'))
from Services.Operation_crop.pipeline import run_pipeline


def process_post_processing(queue_manager, control_post_processing):
    """Процесс пост-обработки. Использует regions + region_chains из controls."""
    print("Процесс пост-обработки запущен")

    try:
        queue_manager.process_ready_queue.put("proc_post_processing")
    except Exception as e:
        print(f"Error sending ready signal: {e}")

    # Параметры по умолчанию
    controls = {
        "enable_post_processing": False,
        "regions": [],  # [{name, x1, y1, x2, y2}, ...]
        "region_chains": {},  # {region_name: [{processor_id, params}, ...]}
        "view_mode": "main",  # "main" | "region" | "list"
        "selected_region": None,
    }

    while not queue_manager.stop_event.is_set():
        # --- Читаем управление ---
        try:
            new_controls = control_post_processing.get_nowait()
            controls.update(new_controls)
        except Empty:
            pass

        # --- Читаем кадр ---
        try:
            data_frame = queue_manager.post_processor_queue.get_nowait()
        except Empty:
            time.sleep(0.01)
            continue

        if not controls.get("enable_post_processing", False):
            queue_manager.remove_old_frame_if_full(queue_manager.display_queue)
            queue_manager.display_queue.put(data_frame)
            continue

        # --- Пайплайн ---
        post_start = time.time()
        id_memory = data_frame["id_memory"]
        capture_time = data_frame.get("capture_time", post_start)

        if "timestamps" not in data_frame:
            data_frame["timestamps"] = {}
        data_frame["timestamps"]["post_processing_start"] = post_start

        frames = queue_manager.memory_manager.read_images("process_data", id_memory)
        if frames is None or len(frames) == 0:
            continue

        processed_frame = frames[0]
        regions = controls.get("regions", [])
        region_chains = controls.get("region_chains", {})
        view_mode = controls.get("view_mode", "main")
        selected_region = controls.get("selected_region")

        # Этап 1: Вырез областей
        # Этап 2: Цепочка для каждой области
        # Этап 3: Объединение
        try:
            result_image, results_list = run_pipeline(
                processed_frame, regions, region_chains
            )
        except Exception as e:
            print(f"Pipeline error: {e}")
            import traceback
            traceback.print_exc()
            result_image = processed_frame.copy()
            results_list = []

        # Выбор что показывать по view_mode
        if view_mode == "region" and selected_region and results_list:
            for r in results_list:
                if r["name"] == selected_region:
                    display_frame = r["image"]
                    break
            else:
                display_frame = result_image
        elif view_mode == "list" and results_list:
            # Показываем объединённый (можно позже сделать коллаж)
            display_frame = result_image
        else:
            display_frame = result_image

        post_end = time.time()
        data_frame["timestamps"]["post_processing_end"] = post_end
        data_frame["post_processing_time"] = post_end - post_start
        data_frame["post_processed"] = True
        data_frame["results_list"] = [
            {"name": r["name"], "pos": r["pos"]} for r in results_list
        ]

        if "processing_time" in data_frame:
            data_frame["processing_time"] += data_frame["post_processing_time"]
        else:
            data_frame["processing_time"] = data_frame["post_processing_time"]
        data_frame["total_time_from_capture"] = post_end - capture_time

        queue_manager.memory_manager.write_images([display_frame], "process_data", id_memory)
        queue_manager.remove_old_frame_if_full(queue_manager.display_queue)
        queue_manager.display_queue.put(data_frame)


def main(queue_manager, control_post_processing):
    process_post_processing(queue_manager, control_post_processing)
