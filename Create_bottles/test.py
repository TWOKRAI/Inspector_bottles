import cv2
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO



frame = cv2.imread('Create_bottles/test_cap.jpg')
frame_gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

# Создаем окно для трекбаров
cv2.namedWindow('Parameters')
cv2.resizeWindow('Parameters', 800, 400)

# Создаем окно для отображения результатов
cv2.namedWindow('Line Detection')
cv2.resizeWindow('Line Detection', 1200, 800)

# Инициализация параметров
canny1 = 20
canny2 = 60
hough_thresh = 30
min_length = 110
max_gap = 50
angle_tol = 5
morph_size = 15

# Создаем трекбары
cv2.createTrackbar('Canny1', 'Parameters', canny1, 255, lambda x: None)
cv2.createTrackbar('Canny2', 'Parameters', canny2, 255, lambda x: None)
cv2.createTrackbar('HoughThresh', 'Parameters', hough_thresh, 200, lambda x: None)
cv2.createTrackbar('MinLength', 'Parameters', min_length, 300, lambda x: None)
cv2.createTrackbar('MaxGap', 'Parameters', max_gap, 100, lambda x: None)
cv2.createTrackbar('AngleTol', 'Parameters', angle_tol, 30, lambda x: None)
cv2.createTrackbar('MorphSize', 'Parameters', morph_size, 50, lambda x: None)

def matplotlib_figure_to_opencv(fig):
    """Конвертирует matplotlib figure в изображение OpenCV"""
    # Сохраняем рисунок в буфер памяти
    buf = BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=100)
    buf.seek(0)
    
    # Читаем изображение из буфера
    img_arr = np.frombuffer(buf.getvalue(), dtype=np.uint8)
    buf.close()
    
    # Декодируем изображение
    img = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)
    return img

def detect_horizontal_lines(image_bw, canny_threshold1, canny_threshold2, hough_threshold,
                           min_line_length, max_line_gap, angle_tolerance, morph_size, debug=False):
    """
    Обнаруживает горизонтальные линии на черно-белом изображении
    """
    # 1. Улучшение контраста
    equ = cv2.equalizeHist(image_bw)
    
    # 2. Гауссово размытие
    blurred = cv2.GaussianBlur(equ, (5, 5), 0)
    
    # 3. Детектирование границ
    edges = cv2.Canny(blurred, canny_threshold1, canny_threshold2)
    
    # 4. Морфологические операции
    kernel_horizontal = np.ones((1, morph_size), np.uint8)
    enhanced = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel_horizontal)
    
    # 5. Преобразование Хафа
    lines = cv2.HoughLinesP(
        enhanced,
        rho=1,
        theta=np.pi/180,
        threshold=hough_threshold,
        minLineLength=min_line_length,
        maxLineGap=max_line_gap
    )
    
    horizontal_lines = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line[0]
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            if (abs(angle) < angle_tolerance) or (abs(angle) > 180 - angle_tolerance):
                horizontal_lines.append((x1, y1, x2, y2))
    
    return horizontal_lines, edges, enhanced

while True:
    # Получаем значения трекбаров
    canny1 = cv2.getTrackbarPos('Canny1', 'Parameters')
    canny2 = cv2.getTrackbarPos('Canny2', 'Parameters')
    hough_thresh = cv2.getTrackbarPos('HoughThresh', 'Parameters')
    min_length = cv2.getTrackbarPos('MinLength', 'Parameters')
    max_gap = cv2.getTrackbarPos('MaxGap', 'Parameters')
    angle_tol = cv2.getTrackbarPos('AngleTol', 'Parameters')
    morph_size = max(1, cv2.getTrackbarPos('MorphSize', 'Parameters'))
    
    # Обнаружение линий
    horizontal_lines, edges, enhanced = detect_horizontal_lines(
        frame_gray,
        canny_threshold1=canny1,
        canny_threshold2=canny2,
        hough_threshold=hough_thresh,
        min_line_length=min_length,
        max_line_gap=max_gap,
        angle_tolerance=angle_tol,
        morph_size=morph_size,
        debug=True
    )
    
    # Создаем график с помощью matplotlib
    fig = plt.figure(figsize=(15, 10))
    
    plt.subplot(221)
    plt.imshow(frame_gray, cmap='gray')
    plt.title("Original Image")
    plt.axis('off')
    
    plt.subplot(222)
    plt.imshow(edges, cmap='gray')
    plt.title(f"Canny Edges (T1={canny1}, T2={canny2})")
    plt.axis('off')
    
    plt.subplot(223)
    plt.imshow(enhanced, cmap='gray')
    plt.title(f"Enhanced Lines (MorphSize={morph_size})")
    plt.axis('off')
    
    plt.subplot(224)
    debug_img = cv2.cvtColor(frame_gray, cv2.COLOR_GRAY2BGR)
    for line in horizontal_lines:
        x1, y1, x2, y2 = line
        cv2.line(debug_img, (x1, y1), (x2, y2), (0, 0, 255), 2)
    plt.imshow(cv2.cvtColor(debug_img, cv2.COLOR_BGR2RGB))
    plt.title(f"Detected: {len(horizontal_lines)} lines\n"
              f"HoughThresh={hough_thresh}, MinLength={min_length}, MaxGap={max_gap}, AngleTol={angle_tol}")
    plt.axis('off')
    
    plt.tight_layout()
    
    # Конвертируем matplotlib figure в OpenCV изображение
    plot_img = matplotlib_figure_to_opencv(fig)
    plt.close(fig)  # Закрываем figure чтобы не накапливать в памяти
    
    # Отображаем результат
    cv2.imshow('Line Detection', plot_img)
    
    # Проверка клавиши выхода
    key = cv2.waitKey(30) & 0xFF
    if key == 27:  # ESC
        break

cv2.destroyAllWindows()