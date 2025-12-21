import os
import torch
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
from PIL import Image
from src.shared.logging import get_logger

logger = get_logger(__name__)

class Sam2Adapter:
    def __init__(self, checkpoint_path: str, model_cfg: str = "sam2_hiera_s.yaml"):
        self.checkpoint_path = checkpoint_path
        self.model_cfg = model_cfg
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.predictor = None

    def _load_model(self):
        if self.predictor is None:
            logger.info(f"Loading SAM 2 model from {self.checkpoint_path}...")
            try:
                from sam2.build_sam import build_sam2_video_predictor
                self.predictor = build_sam2_video_predictor(self.model_cfg, self.checkpoint_path, device=self.device)
                logger.info("SAM 2 model loaded.")
            except ImportError as e:
                logger.error(f"Failed to import SAM 2: {e}")
                raise ImportError("SAM 2 is not installed. Please install it from https://github.com/facebookresearch/sam2")
            except Exception as e:
                logger.error(f"Failed to load SAM 2 model: {e}")
                raise RuntimeError(f"Failed to load SAM 2 model: {e}")

    def _unload_model(self):
        if self.predictor is not None:
            del self.predictor
            self.predictor = None
            torch.cuda.empty_cache()
            logger.info("SAM 2 model unloaded to free VRAM.")

    def generate_masks(self, video_path: str, bboxes_by_frame: Dict[int, List[List[float]]], output_mask_dir: Path):
        """
        :param video_path: Путь к видео
        :param bboxes_by_frame: Словарь {frame_idx: [[x1, y1, x2, y2], ...]}
        :param output_mask_dir: Куда сохранять ч/б маски
        """
        self._load_model()
        
        # SAM 2 требует директорию с кадрами (jpeg/png), а не видеофайл. 
        # Если SAM2 не умеет читать видео напрямую в текущей версии, нужно убедиться, 
        # что мы передаем ему кадры, или используем его video state.
        # В этой реализации предполагаем инициализацию state из видео (если поддерживается) 
        # или работаем через inference_state.
        
        # NOTE: SAM 2 Video API требует инициализации состояния
        try:
            inference_state = self.predictor.init_state(video_path=video_path)
        except Exception as e:
            logger.error(f"SAM 2 failed to initialize state from video: {e}")
            logger.info("Trying alternative approach: extracting frames first...")
            # Fallback: extract frames and process as images
            return self._generate_masks_fallback(video_path, bboxes_by_frame, output_mask_dir)
        
        logger.info("Propagating masks with SAM 2...")

        # 1. Добавляем промпты (квадраты от OCR)
        for frame_idx, bboxes in bboxes_by_frame.items():
            for bbox in bboxes:
                # box expects [x1, y1, x2, y2]
                self.predictor.add_new_points_or_box(
                    inference_state=inference_state,
                    frame_idx=frame_idx,
                    obj_id=1,  # Все субтитры считаем одним объектом для маски
                    box=np.array(bbox, dtype=np.float32)
                )

        # 2. Пропагация (трекинг) по всему видео
        # video_res - генератор, возвращает маски покадрово
        output_mask_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            for out_frame_idx, out_obj_ids, out_mask_logits in self.predictor.propagate_in_video(inference_state):
                # Преобразуем logits в бинарную маску
                mask = (out_mask_logits[0] > 0.0).cpu().numpy().squeeze().astype(np.uint8) * 255
                
                # Сохраняем маску
                mask_img = Image.fromarray(mask, mode='L')
                mask_img.save(output_mask_dir / f"{out_frame_idx:05d}.png")
        except Exception as e:
            logger.error(f"SAM 2 propagation failed: {e}")
            raise RuntimeError(f"SAM 2 propagation failed: {e}")

        # Чистим память
        self._unload_model()
        return output_mask_dir

    def _generate_masks_fallback(self, video_path: str, bboxes_by_frame: Dict[int, List[List[float]]], output_mask_dir: Path):
        """
        Fallback method if SAM 2 video API doesn't work.
        Extracts frames and processes them individually.
        """
        import cv2
        import tempfile
        
        logger.info("Using fallback frame-by-frame processing...")
        
        # Create temporary directory for frames
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_frames_dir = Path(temp_dir) / "frames"
            temp_frames_dir.mkdir(parents=True, exist_ok=True)
            
            # Extract frames from video
            cap = cv2.VideoCapture(video_path)
            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_path = temp_frames_dir / f"{frame_idx:05d}.jpg"
                cv2.imwrite(str(frame_path), frame)
                frame_idx += 1
            
            cap.release()
            
            if frame_idx == 0:
                raise ValueError(f"No frames extracted from video: {video_path}")
            
            logger.info(f"Extracted {frame_idx} frames from video")
            
            # Process each frame with bounding boxes
            output_mask_dir.mkdir(parents=True, exist_ok=True)
            
            for frame_idx in range(frame_idx):
                if frame_idx in bboxes_by_frame:
                    frame_path = temp_frames_dir / f"{frame_idx:05d}.jpg"
                    frame = cv2.imread(str(frame_path))
                    if frame is None:
                        continue
                    
                    # Create mask for this frame
                    h, w = frame.shape[:2]
                    mask = np.zeros((h, w), dtype=np.uint8)
                    
                    for bbox in bboxes_by_frame[frame_idx]:
                        x1, y1, x2, y2 = map(int, bbox)
                        # Draw rectangle on mask
                        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
                    
                    # Save mask
                    mask_img = Image.fromarray(mask, mode='L')
                    mask_img.save(output_mask_dir / f"{frame_idx:05d}.png")
                else:
                    # Create empty mask for frames without text
                    h, w = 1080, 1920  # Default dimensions, adjust as needed
                    mask = np.zeros((h, w), dtype=np.uint8)
                    mask_img = Image.fromarray(mask, mode='L')
                    mask_img.save(output_mask_dir / f"{frame_idx:05d}.png")
        
        self._unload_model()
        return output_mask_dir
