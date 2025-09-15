import cv2
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO

def matplotlib_figure_to_opencv(fig):
    """Конвертирует matplotlib figure в изображение OpenCV"""
    buf = BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    buf.seek(0)
    img_arr = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    buf.close()
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    return img


def add_white_padding(frame, padding_height=5):
    # Получаем размеры изображения
    height, width = frame.shape[:2]

    # Создаем новое изображение с дополнительными строками белых пикселей внизу
    new_height = height + padding_height
    new_frame = np.ones((new_height, width, 3), dtype=np.uint8) * 255  # Белый фон

    # Копируем исходное изображение в новую область
    new_frame[:height, :, :] = frame

    return new_frame


def analyze_contours(image_bw,
                     canny_threshold1=30,
                     canny_threshold2=90,
                     blur_kernel_size=5,
                     morph_kernel_size=5,  # Размер ядра для морфологических операций
                     contour_mode=cv2.RETR_EXTERNAL,
                     contour_method=cv2.CHAIN_APPROX_SIMPLE,
                     min_area=100,
                     min_length=50,
                     debug=False):
    """
    Анализирует и замыкает контуры на черно-белом изображении.
    """
    debug_images = {}

    # Предварительная обработка: размытие
    if blur_kernel_size > 0:
        image_processed = cv2.GaussianBlur(image_bw, (blur_kernel_size, blur_kernel_size), 0)
    else:
        image_processed = image_bw.copy()

    if debug:
        debug_images['blurred'] = image_processed

    # Детектирование границ
    edges = cv2.Canny(image_processed, canny_threshold1, canny_threshold2)

    # Морфологическое закрытие для соединения границ
    if morph_kernel_size > 0:
        kernel = np.ones((morph_kernel_size, morph_kernel_size), np.uint8)
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    if debug:
        debug_images['edges'] = edges

    # Поиск контуров
    contours, hierarchy = cv2.findContours(edges, contour_mode, contour_method)

    # Анализ контуров
    contours_info = []

    for contour in contours:
        # Замыкание контура (если это еще не сделано)
        contour_closed = contour
        if not cv2.isContourConvex(contour):
            contour_closed = cv2.convexHull(contour)

        # Вычисляем площадь и длину замкнутого контура
        area = cv2.contourArea(contour_closed)
        length = cv2.arcLength(contour_closed, closed=True)

        # Фильтрация по порогам
        if area >= min_area and length >= min_length:
            contours_info.append({
                'contour': contour_closed,
                'area': area,
                'length': length
            })

    # Создаем изображение с контурами для отладки
    if debug:
        if len(image_bw.shape) == 2:
            contour_image = cv2.cvtColor(image_bw, cv2.COLOR_GRAY2BGR)
        else:
            contour_image = image_bw.copy()

        cv2.drawContours(contour_image, contours, -1, (0, 255, 0), 2)

        for info in contours_info:
            contour = info['contour']
            cv2.drawContours(contour_image, [contour], -1, (0, 0, 255), 3)
            x, y, w, h = cv2.boundingRect(contour)
            # cv2.putText(contour_image, f"A:{info['area']:.0f}", (x, y-20),
            #             cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
            # cv2.putText(contour_image, f"L:{info['length']:.0f}", (x, y-5),
            #             cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        debug_images['contours'] = contour_image

    return (contours_info, debug_images) if debug else contours_info

def main():
    frame = cv2.imread('Create_bottles/test_cap.jpg')
    frame_with_padding = add_white_padding(frame)
    
    frame_gray = cv2.cvtColor(frame_with_padding, cv2.COLOR_BGR2GRAY)

    cv2.namedWindow('Parameters')
    cv2.resizeWindow('Parameters', 800, 600)

    # Параметры
    canny1 = 30
    canny2 = 90
    min_area = 100
    min_length = 50
    blur_kernel = 5
    morph_kernel = 5  # Новый параметр для морфологии
    contour_mode_idx = 0
    contour_method_idx = 0

    # Создаем трекбары
    cv2.createTrackbar('Canny1', 'Parameters', canny1, 255, lambda x: None)
    cv2.createTrackbar('Canny2', 'Parameters', canny2, 255, lambda x: None)
    cv2.createTrackbar('MinArea', 'Parameters', min_area, 1000, lambda x: None)
    cv2.createTrackbar('MinLength', 'Parameters', min_length, 500, lambda x: None)
    cv2.createTrackbar('BlurKernel', 'Parameters', blur_kernel, 15, lambda x: None)
    cv2.createTrackbar('MorphKernel', 'Parameters', morph_kernel, 15, lambda x: None)  # Новый трекбар
    cv2.createTrackbar('ContourMode', 'Parameters', contour_mode_idx, 3, lambda x: None)
    cv2.createTrackbar('ContourMethod', 'Parameters', contour_method_idx, 3, lambda x: None)

    contour_modes = {
        0: cv2.RETR_EXTERNAL,
        1: cv2.RETR_LIST,
        2: cv2.RETR_TREE,
        3: cv2.RETR_CCOMP
    }
    contour_methods = {
        0: cv2.CHAIN_APPROX_SIMPLE,
        1: cv2.CHAIN_APPROX_NONE,
        2: cv2.CHAIN_APPROX_TC89_L1,
        3: cv2.CHAIN_APPROX_TC89_KCOS
    }

    while True:
        canny1 = cv2.getTrackbarPos('Canny1', 'Parameters')
        canny2 = cv2.getTrackbarPos('Canny2', 'Parameters')
        min_area = cv2.getTrackbarPos('MinArea', 'Parameters')
        min_length = cv2.getTrackbarPos('MinLength', 'Parameters')
        blur_kernel = cv2.getTrackbarPos('BlurKernel', 'Parameters')
        morph_kernel = cv2.getTrackbarPos('MorphKernel', 'Parameters')  # Получаем значение трекбара
        contour_mode_idx = cv2.getTrackbarPos('ContourMode', 'Parameters')
        contour_method_idx = cv2.getTrackbarPos('ContourMethod', 'Parameters')

        contour_mode = contour_modes.get(contour_mode_idx, cv2.RETR_EXTERNAL)
        contour_method = contour_methods.get(contour_method_idx, cv2.CHAIN_APPROX_SIMPLE)

        contours_info, debug_images = analyze_contours(
            image_bw=frame_gray,
            canny_threshold1=canny1,
            canny_threshold2=canny2,
            blur_kernel_size=blur_kernel if blur_kernel > 0 else 0,
            morph_kernel_size=morph_kernel if morph_kernel > 0 else 0,  # Передаем новый параметр
            contour_mode=contour_mode,
            contour_method=contour_method,
            min_area=min_area,
            min_length=min_length,
            debug=True
        )

        fig = plt.figure(figsize=(15, 10))

        plt.subplot(231)
        plt.imshow(frame_gray, cmap='gray')
        plt.title("Original Image")
        plt.axis('off')

        plt.subplot(232)
        if 'blurred' in debug_images:
            plt.imshow(debug_images['blurred'], cmap='gray')
            plt.title(f"Blurred (Kernel={blur_kernel})")
        else:
            plt.imshow(frame_gray, cmap='gray')
            plt.title("No Blur Applied")
        plt.axis('off')

        plt.subplot(233)
        plt.imshow(debug_images['edges'], cmap='gray')
        plt.title(f"Canny Edges (T1={canny1}, T2={canny2})")
        plt.axis('off')

        plt.subplot(234)
        plt.imshow(cv2.cvtColor(debug_images['contours'], cv2.COLOR_BGR2RGB))
        plt.title(f"Detected Contours: {len(contours_info)}")
        plt.axis('off')

        plt.subplot(235)
        mode_names = {0: 'RETR_EXTERNAL', 1: 'RETR_LIST', 2: 'RETR_TREE', 3: 'RETR_CCOMP'}
        method_names = {0: 'CHAIN_APPROX_SIMPLE', 1: 'CHAIN_APPROX_NONE',
                       2: 'CHAIN_APPROX_TC89_L1', 3: 'CHAIN_APPROX_TC89_KCOS'}

        plt.text(0.1, 0.9, f"Contour Mode: {mode_names[contour_mode_idx]}", fontsize=12, transform=plt.gca().transAxes)
        plt.text(0.1, 0.7, f"Contour Method: {method_names[contour_method_idx]}", fontsize=12, transform=plt.gca().transAxes)
        
        areas = [info['area'] for info in contours_info]
        plt.text(0.1, 0.5, f"Max Area: {max(areas)}", fontsize=12, transform=plt.gca().transAxes)
        plt.text(0.1, 0.3, f"Min Length: {min_length}", fontsize=12, transform=plt.gca().transAxes)
        plt.text(0.1, 0.1, f"Total Contours: {len(contours_info)}", fontsize=12, transform=plt.gca().transAxes)
        plt.axis('off')

        plt.subplot(236)
        if contours_info:
            areas = [info['area'] for info in contours_info]
            plt.barh(range(len(areas)), areas, color='skyblue')
            plt.xlabel('Area')
            plt.ylabel('Contour Index')
            plt.title('Contour Areas')
        else:
            plt.text(0.5, 0.5, 'No contours found', ha='center', va='center', transform=plt.gca().transAxes)
            plt.axis('off')

        plt.tight_layout()

        plot_img = matplotlib_figure_to_opencv(fig)
        plt.close(fig)

        cv2.imshow('Contour Analysis', plot_img)

        key = cv2.waitKey(30) & 0xFF
        if key == 27:  # ESC
            break
        elif key == ord('s'):
            print(f"Текущие параметры: Canny1={canny1}, Canny2={canny2}, MinArea={min_area}, MinLength={min_length}")
            print(f"BlurKernel={blur_kernel}, MorphKernel={morph_kernel}, ContourMode={mode_names[contour_mode_idx]}, ContourMethod={method_names[contour_method_idx]}")

    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
