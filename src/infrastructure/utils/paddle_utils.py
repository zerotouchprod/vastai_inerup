"""
Утилиты для работы с PaddleOCR и подавления лишнего вывода.
"""

import os
import sys
import logging
import warnings
from contextlib import redirect_stderr, redirect_stdout
import io


def setup_paddle_logging():
    """
    Настраивает подавление логов PaddleOCR и связанных библиотек.
    Должна быть вызвана ДО импорта PaddleOCR.
    """
    warnings.filterwarnings('ignore')
    
    # Настраиваем все возможные логгеры PaddleOCR
    for logger_name in ['ppocr', 'paddleocr', 'paddle', 'paddlex', 'paddle.nn', 'paddle.fluid']:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    
    # Также отключаем логирование для root логгера от Paddle
    logging.getLogger().setLevel(logging.WARNING)
    
    # Устанавливаем переменные окружения для подавления вывода
    os.environ['PADDLEOCR_LOG_LEVEL'] = '4'  # Максимальное подавление
    os.environ['LOG_LEVEL'] = '4'
    os.environ['PADDLE_LOG_LEVEL'] = '4'
    os.environ['GLOG_minloglevel'] = '3'  # 0=INFO, 1=WARNING, 2=ERROR, 3=FATAL
    
    # Дополнительная настройка после импорта paddle (если доступен)
    try:
        import paddle
        # Проверяем, существует ли метод set_log_level
        if hasattr(paddle, 'set_log_level'):
            paddle.set_log_level(4)  # 4=CRITICAL (максимальное подавление)
        else:
            # Альтернативный способ подавления логов
            logging.getLogger('paddle').setLevel(logging.WARNING)
    except ImportError:
        pass


class SuppressPaddleOutput:
    """
    Контекстный менеджер для подавления вывода PaddleOCR.
    
    Использование:
    ```python
    with SuppressPaddleOutput():
        ocr = PaddleOCR(...)
        result = ocr.ocr(image)
    ```
    """
    
    def __enter__(self):
        self._original_stderr = sys.stderr
        self._original_stdout = sys.stdout
        self._null_stream = io.StringIO()
        sys.stderr = self._null_stream
        sys.stdout = self._null_stream
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stderr = self._original_stderr
        sys.stdout = self._original_stdout


def init_paddle_ocr(lang: str = 'en', use_gpu_for_ocr: bool = False, use_angle_cls: bool = False):
    """
    Инициализирует PaddleOCR с минимальными параметрами и подавлением вывода.
    
    Args:
        lang: Язык для OCR
        use_gpu_for_ocr: Использовать GPU для OCR если доступно
        use_angle_cls: Использовать классификатор угла поворота
    
    Returns:
        Экземпляр PaddleOCR или None если импорт не удался
    """
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        return None
    
    # Проверяем доступность GPU для OCR
    try:
        import torch
        ocr_device = 'gpu' if (use_gpu_for_ocr and torch.cuda.is_available()) else 'cpu'
    except ImportError:
        ocr_device = 'cpu'
    
    # Используем абсолютно минимальный набор параметров
    ocr_params = {
        'lang': lang,
        'use_angle_cls': use_angle_cls,
        'det_model_dir': None,   # Use default mobile model
        'rec_model_dir': None,   # Use default mobile model
        'cls_model_dir': None,   # No classification model
    }
    
    # Используем контекстный менеджер для полного подавления вывода
    with SuppressPaddleOutput():
        # Временно повышаем уровень логирования для подавления сообщений при инициализации
        original_level = logging.getLogger('ppocr').level
        logging.getLogger('ppocr').setLevel(logging.ERROR)
        
        try:
            # Инициализируем PaddleOCR с минимальными параметрами
            ocr = PaddleOCR(**ocr_params)
            return ocr
        finally:
            # Восстанавливаем исходный уровень логирования
            logging.getLogger('ppocr').setLevel(original_level)
