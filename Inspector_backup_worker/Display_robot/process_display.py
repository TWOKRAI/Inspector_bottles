import cv2
import time
from queue import Empty

from Testing.queues_module import clear_queue

def display_frames(queue_manager, stop_event):
    cv2.namedWindow('Detected Circles')
    cv2.createTrackbar('Draw', 'Detected Circles', 1, 1, lambda x: None)
    cv2.createTrackbar('Circles', 'Detected Circles', 1, 1, lambda x: None)
    cv2.createTrackbar('Rectangles', 'Detected Circles', 1, 1, lambda x: None)
    cv2.createTrackbar('Record_video', 'Detected Circles', 0, 1, lambda x: None)

    dp = 1.2
    minDist = 20
    param1 = 50
    param2 = 30
    minRadius = 27
    maxRadius = 40

    cv2.namedWindow('Circle Parameters')
    cv2.createTrackbar('dp', 'Circle Parameters', int(dp * 10), 20, lambda x: None)
    cv2.createTrackbar('minDist', 'Circle Parameters', minDist, 100, lambda x: None)
    cv2.createTrackbar('param1', 'Circle Parameters', param1, 200, lambda x: None)
    cv2.createTrackbar('param2', 'Circle Parameters', param2, 200, lambda x: None)
    cv2.createTrackbar('minRadius', 'Circle Parameters', minRadius, 100, lambda x: None)
    cv2.createTrackbar('maxRadius', 'Circle Parameters', maxRadius, 100, lambda x: None)

    cv2.namedWindow('Cropped Area')
    cv2.createTrackbar('height', 'Cropped Area', 250, 600, lambda x: None)
    cv2.createTrackbar('y_delta', 'Cropped Area', 50, 100, lambda x: None)
    cv2.createTrackbar('x_delta', 'Cropped Area', 21, 100, lambda x: None)
    cv2.createTrackbar('x_min', 'Cropped Area', 150, 1280, lambda x: None)
    cv2.createTrackbar('x_max', 'Cropped Area', 750, 1280, lambda x: None)

    cv2.namedWindow('parameters', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('parameters', 450, 700)
    cv2.createTrackbar('HL', 'parameters', 0, 255, lambda x: None)
    cv2.createTrackbar('SL', 'parameters', 0, 255, lambda x: None)
    cv2.createTrackbar('VL', 'parameters', 200, 255, lambda x: None)
    cv2.createTrackbar('HM', 'parameters', 255, 255, lambda x: None)
    cv2.createTrackbar('SM', 'parameters', 255, 255, lambda x: None)
    cv2.createTrackbar('VM', 'parameters', 255, 255, lambda x: None)
    cv2.createTrackbar('AREA', 'parameters', 2600, 5200, lambda x: None)
    cv2.createTrackbar('SAVE_IMAGE', 'parameters', 0, 1, lambda x: None)
    cv2.createTrackbar('snap_y', 'parameters', 200, 600, lambda x: None)
    cv2.createTrackbar('shift', 'parameters', 717, 7000, lambda x: None)
    cv2.createTrackbar('shift_y', 'parameters', 120, 1000, lambda x: None)
    cv2.createTrackbar('mode', 'parameters', 1, 1, lambda x: None)
    cv2.createTrackbar('Processing', 'parameters', 1, 1, lambda x: None)
    cv2.createTrackbar('Neuron', 'parameters', 1, 1, lambda x: None)
    cv2.createTrackbar('Neuron_enable_2', 'parameters', 0, 1, lambda x: None)  
    cv2.createTrackbar('fps', 'parameters', 5, 25, lambda x: None)

    top = 150 #0
    bottom = 550 #570
    left = 180
    right = 1075

    next_circles_data = {}
    total_circles = 0
    frame_buffer = []
    buffer_size = 0

    buffer_ready = False

    print("Дисплей запущен")

    while not stop_event.is_set():
        control = {
            'top': top, 
            'bottom': bottom,
            'left': left, 
            'right': right,
            'hl': cv2.getTrackbarPos('HL', 'parameters'),
            'sl': cv2.getTrackbarPos('SL', 'parameters'),
            'vl': cv2.getTrackbarPos('VL', 'parameters'),
            'hm': cv2.getTrackbarPos('HM', 'parameters'),
            'sm': cv2.getTrackbarPos('SM', 'parameters'),
            'vm': cv2.getTrackbarPos('VM', 'parameters'),
            'area_threshold': cv2.getTrackbarPos('AREA', 'parameters'),
            'save_image': cv2.getTrackbarPos('SAVE_IMAGE', 'parameters'),
            'snap_y': cv2.getTrackbarPos('snap_y', 'parameters'),
            'shift': cv2.getTrackbarPos('shift', 'parameters'),
            'shift_y': cv2.getTrackbarPos('shift_y', 'parameters'),
            'mode': cv2.getTrackbarPos('mode', 'parameters'),
            'processing_enabled': cv2.getTrackbarPos('Processing', 'parameters'),
            'processing_neuroun': cv2.getTrackbarPos('Neuron', 'parameters'),
            'y_delta': cv2.getTrackbarPos('y_delta', 'Cropped Area'),
            'x_delta': cv2.getTrackbarPos('x_delta', 'Cropped Area'),
            'x_min': cv2.getTrackbarPos('x_min', 'Cropped Area'),
            'x_max': cv2.getTrackbarPos('x_max', 'Cropped Area'),
            'dp': cv2.getTrackbarPos('dp', 'Circle Parameters') / 10.0,
            'minDist': cv2.getTrackbarPos('minDist', 'Circle Parameters'),
            'param1': cv2.getTrackbarPos('param1', 'Circle Parameters'),
            'param2': cv2.getTrackbarPos('param2', 'Circle Parameters'),
            'minRadius': cv2.getTrackbarPos('minRadius', 'Circle Parameters'),
            'maxRadius': cv2.getTrackbarPos('maxRadius', 'Circle Parameters'),
            'height': cv2.getTrackbarPos('height', 'Cropped Area'),
            'fps': cv2.getTrackbarPos('fps', 'parameters'),
            'record_video': cv2.getTrackbarPos('Record_video', 'Detected Circles')
        }

        queue_manager.control_display.put(control)

        control_camera = {
            'draw': cv2.getTrackbarPos('Draw', 'Detected Circles'),
            'circles': cv2.getTrackbarPos('Circles', 'Detected Circles'),
            'rectangles': cv2.getTrackbarPos('Rectangles', 'Detected Circles'),
            'record_video': cv2.getTrackbarPos('Record_video', 'Detected Circles')
        }

        queue_manager.control_camera.put(control_camera)

        try:
            data = queue_manager.result_frame_queue.get(timeout=1)
        except Empty:
            print("Очередь result_frame_queue пуста")
            continue

        clear_queue(queue_manager.result_frame_queue, 1)

        # circles_draw = cv2.getTrackbarPos('Circles', 'Detected Circles')
        # rectangle_draw = cv2.getTrackbarPos('Rectangles', 'Detected Circles')

        frame = data['frame']
        frame_crop = data['frame_crop']
        circles_info = data['circles_info']
        processing_time = data['processing_time']
        snap_y = data['snap_y']
        y_delta = data['y_delta']
        frame_id = data['frame_id']
        total = data['total']
        total_all = data['total_all']
        x_min = data['x_min']
        x_max = data['x_max']

        size_image_cnn = 72
        size_image_cnn_2 = int(size_image_cnn/2) + 4
        
        if control_camera['draw'] == 1:
            for (frame_id_circle, img, img_cnn, x, y, r, label, color) in circles_info:
                if frame_id_circle == frame_id:
                    if control_camera['circles'] == 1:
                        cv2.circle(frame, (x + 1, y + 1), r, (0, 0, 0), 3)
                        cv2.circle(frame, (x, y), r, color, 3)

                    if control_camera['rectangles'] == 1:
                        shadow_delta = 2
                        cv2.rectangle(frame, (x - size_image_cnn_2 + shadow_delta, y - size_image_cnn_2 + shadow_delta), (x + size_image_cnn_2 + shadow_delta, y + size_image_cnn_2 + shadow_delta), (30, 30, 30), 1)
                        cv2.rectangle(frame, (x - size_image_cnn_2, y - size_image_cnn_2), (x + size_image_cnn_2, y + size_image_cnn_2), (255, 0, 0), 2)
                    
                    if control_camera['circles'] == 1 or control_camera['rectangles'] == 1: 
                        cv2.putText(frame, label, (x - 15 + 1, y - r - 10 + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
                        cv2.putText(frame, label, (x - 15, y - r - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

            if control_camera['record_video'] == 0:
                cv2.line(frame, (0, snap_y), (frame.shape[1], snap_y), (255, 0, 0), 2)
                cv2.line(frame, (x_min, snap_y - y_delta), (x_max, snap_y - y_delta), (255, 255, 0), 2)
                cv2.line(frame, (x_min, snap_y + y_delta), (x_max, snap_y + y_delta), (255, 255, 0), 2)

                cv2.line(frame, (x_min, 0), (x_min, frame.shape[0] - 72), (0, 255, 0), 2)
                cv2.line(frame, (x_max, 0), (x_max, frame.shape[0] - 72), (0, 255, 0), 2)

                cv2.putText(frame, f'Total Circles: {total}', (frame.shape[1] - 200, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
                cv2.putText(frame, f'total_all: {total_all}', (frame.shape[1] - 200, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)

        cv2.putText(frame, f'Processing Time: {processing_time:.2f} ms', (22, 52), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        cv2.putText(frame, f'Processing Time: {processing_time:.2f} ms', (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

        if control_camera['record_video'] == 1:
            cv2.putText(frame, f'RECORD', (51, 81), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

        cv2.imshow('Detected Circles', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            stop_event.set()
            break

    cv2.destroyAllWindows()
    print("Дисплей завершен")
