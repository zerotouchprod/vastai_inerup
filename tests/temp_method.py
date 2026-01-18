def _process_dynamic_crop(self, frames: torch.Tensor, masks: torch.Tensor) -> torch.Tensor:
        """
        Process frames using dynamic mask-guided tiling.
        Identify subtitle bounding box across the chunk, crop with padding and grid snap,
        process only that region, and stitch back.
        
        Args:
            frames: Frames tensor of shape (T, C, H, W)
            masks: Masks tensor of shape (T, 1, H, W)
            
        Returns:
            Processed frames tensor of shape (T, C, H, W)
        """
        T, C, H, W = frames.shape
        
        # 1. Union mask across time dimension
        # masks shape: [T, 1, H, W]
        union_mask = torch.max(masks, dim=0).values.squeeze(0)  # shape [H, W]
        
        # 2. Find non-zero indices
        non_zero = torch.nonzero(union_mask > 0, as_tuple=False)
        if len(non_zero) == 0:
            # No subtitles in this chunk
            logger.debug("No subtitles detected in chunk, returning original frames")
            return frames
        
        # 3. Get bounding box coordinates
        y_min, x_min = non_zero.min(dim=0).values
        y_max, x_max = non_zero.max(dim=0).values
        
        # 4. Apply padding & grid snap (Safe Box)
        pad = self.padding_px
        y1 = max(0, (int(y_min) - pad) // 8 * 8)
        x1 = max(0, (int(x_min) - pad) // 8 * 8)
        y2 = min(H, (int(y_max) + pad + 8) // 8 * 8)
        x2 = min(W, (int(x_max) + pad + 8) // 8 * 8)
        
        # 5. Check safety (don't OOM on full screen text)
        crop_area = (y2 - y1) * (x2 - x1)
        total_area = H * W
        max_safe_pixels = self.max_crop_area_ratio * total_area
        if crop_area > max_safe_pixels:
            logger.warning(
                f"Crop area {crop_area} exceeds safe limit {max_safe_pixels:.0f} "
                f"({self.max_crop_area_ratio*100:.0f}% of frame). Falling back to split processing."
            )
            return self._process_split_frame(frames, masks)
        
        # Log the crop region
        logger.info(
            f"Dynamic Crop: Processing area Y={y1}:{y2}, X={x1}:{x2} "
            f"(Size: {(y2-y1)}x{(x2-x1)})."
        )
        
        # 6. Crop frames and masks
        crop_frames = frames[:, :, y1:y2, x1:x2]
        crop_masks = masks[:, :, y1:y2, x1:x2]
        
        # 7. Process crop
        processed_crop = self.model_adapter.process_chunk(crop_frames, crop_masks)
        
        # Ensure same dtype and device as original frames
        if processed_crop.dtype != frames.dtype:
            processed_crop = processed_crop.to(frames.dtype)
        if processed_crop.device != frames.device:
            processed_crop = processed_crop.to(frames.device)
        
        # 8. Stitch back into full frames
        processed_frames = frames.clone()
        processed_frames[:, :, y1:y2, x1:x2] = processed_crop
        
        return processed_frames
