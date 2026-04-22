"""Workers — переиспользуемые компоненты для process-модулей.

RecorderWorker — запись видео через cv2.VideoWriter (AD-10).
"""

from .recorder_worker import RecorderWorker

__all__ = ["RecorderWorker"]
