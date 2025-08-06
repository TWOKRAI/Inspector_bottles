import time
import cv2

from color_process import ColorDetector


def main(queue_manager):
    print(f'processing_module: RUN')

    detector = ColorDetector()
    

    while True:
        data_frame = queue_manager.input_processing.get()
        
        id_memory = data_frame['id_memory']
        #print(f'processing_module: {id_memory}')

        frames = queue_manager.memory_manager.read_images("camera_data", id_memory)


        detector.get_trackbar_values()

        # Обработка кадра
        processed_frame, mask = detector.process_frame(frames[0])

        frames = [processed_frame]
        
        queue_manager.memory_manager.write_images(frames, "process_data", id_memory)
        queue_manager.input_render.put(data_frame)

        # Отображение результатов
        cv2.imshow('Mask', mask)
        cv2.waitKey(1)

