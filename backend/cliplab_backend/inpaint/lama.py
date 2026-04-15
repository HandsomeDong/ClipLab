from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np


class LaMaInpaintError(RuntimeError):
    pass


class LaMaInpaintRuntime:
    """LaMa (Large Mask Inpainting) runtime with batch processing support."""

    BATCH_SIZE = 4  # Process 4 frames at a time to avoid OOM

    def __init__(self, model_path: Path) -> None:
        self.model_path = model_path
        self.torch = self._import_torch()
        self.device = self._select_device()
        self.model = self._load_model()

    @staticmethod
    def _import_torch():
        try:
            import torch
        except Exception as error:
            raise LaMaInpaintError(
                "LaMa 运行需要安装 torch。可执行 uv sync --project backend --extra sttn。"
            ) from error
        return {"torch": torch}

    def _select_device(self):
        torch = self.torch["torch"]
        if torch.cuda.is_available():
            return torch.device("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    def _load_model(self):
        import torch
        if not self.model_path.exists():
            raise LaMaInpaintError(f"未找到 LaMa 模型文件：{self.model_path}")
        model = torch.jit.load(str(self.model_path), map_location=self.device)
        model.eval()
        return model

    @staticmethod
    def _pad_to_modulo(img: np.ndarray, modulo: int = 8) -> tuple[np.ndarray, tuple[int, int]]:
        """Pad image to be divisible by modulo."""
        h, w = img.shape[:2]
        new_h = ((h + modulo - 1) // modulo) * modulo
        new_w = ((w + modulo - 1) // modulo) * modulo
        if new_h == h and new_w == w:
            return img, (h, w)
        padded = np.zeros((new_h, new_w, 3), dtype=img.dtype)
        padded[:h, :w] = img
        return padded, (h, w)

    def _preprocess(self, image: np.ndarray, mask: np.ndarray, device):
        """Preprocess image and mask for LaMa model."""
        import torch

        # Normalize image to [0, 1]
        if image.dtype == np.uint8:
            image = image.astype(np.float32) / 255.0
        elif image.dtype != np.float32:
            image = image.astype(np.float32)

        # Ensure mask is single channel
        if mask.ndim == 3:
            mask = mask[:, :, 0]

        # Pad to modulo 8
        image, (orig_h, orig_w) = self._pad_to_modulo(image, 8)
        mask, _ = self._pad_to_modulo(mask, 8)

        # Convert to tensor
        image_tensor = torch.from_numpy(image).permute(2, 0, 1).unsqueeze(0).to(device)
        mask_tensor = torch.from_numpy(mask).unsqueeze(0).unsqueeze(0).to(device)
        mask_tensor = (mask_tensor > 0.5).float()

        return image_tensor, mask_tensor, orig_h, orig_w

    def _inpaint_single(self, image: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """Inpaint a single image with LaMa."""
        import torch

        image_tensor, mask_tensor, orig_h, orig_w = self._preprocess(image, mask, self.device)

        with torch.inference_mode():
            inpainted = self.model(image_tensor, mask_tensor)
            result = inpainted[0].permute(1, 2, 0).cpu().numpy()

        result = np.clip(result * 255, 0, 255).astype(np.uint8)
        return result[:orig_h, :orig_w]

    def _inpaint_batch(self, images: list[np.ndarray], masks: list[np.ndarray]) -> list[np.ndarray]:
        """Inpaint a batch of images with LaMa, processing in mini-batches to avoid OOM."""
        import torch

        results = [None] * len(images)

        for batch_start in range(0, len(images), self.BATCH_SIZE):
            batch_end = min(batch_start + self.BATCH_SIZE, len(images))
            batch_images = images[batch_start:batch_end]
            batch_masks = masks[batch_start:batch_end]

            # Preprocess batch
            padded_images = []
            padded_masks = []
            orig_sizes = []

            for img, mask in zip(batch_images, batch_masks):
                img_padded, (orig_h, orig_w) = self._pad_to_modulo(img, 8)
                mask_padded, _ = self._pad_to_modulo(mask, 8)
                padded_images.append(img_padded)
                padded_masks.append(mask_padded)
                orig_sizes.append((orig_h, orig_w))

            # Stack into batches
            images_batch = np.stack(padded_images, axis=0)
            masks_batch = np.stack(padded_masks, axis=0)

            # Convert to tensors
            images_tensor = torch.from_numpy(images_batch).permute(0, 3, 1, 2).float().to(self.device) / 255.0
            masks_tensor = torch.from_numpy(masks_batch).unsqueeze(1).to(self.device)
            masks_tensor = (masks_tensor > 0.5).float()

            # Run inference
            with torch.inference_mode():
                inpainted = self.model(images_tensor, masks_tensor)
                batch_results = inpainted.permute(0, 2, 3, 1).cpu().numpy() * 255

            # Post-process and store results
            for i, result in enumerate(batch_results):
                orig_h, orig_w = orig_sizes[i]
                result = np.clip(result, 0, 255).astype(np.uint8)
                results[batch_start + i] = result[:orig_h, :orig_w]

            # Clear GPU cache
            del images_tensor, masks_tensor, inpainted
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        return results

    def inpaint(self, frames: list[np.ndarray], mask: np.ndarray) -> list[np.ndarray]:
        """Inpaint multiple frames with LaMa model."""
        if not frames:
            return []

        # Prepare crops for each frame
        cropped_frames = []
        cropped_masks = []

        for frame in frames:
            cropped_frames.append(frame)
            cropped_masks.append(mask)

        # Use batch processing for multiple frames
        if len(frames) > 1:
            return self._inpaint_batch(cropped_frames, cropped_masks)
        else:
            return [self._inpaint_single(cropped_frames[0], cropped_masks[0])]


def pad_img_to_modulo(img: np.ndarray, modulo: int = 8) -> np.ndarray:
    """Pad image to be divisible by modulo."""
    h, w = img.shape[:2]
    new_h = ((h + modulo - 1) // modulo) * modulo
    new_w = ((w + modulo - 1) // modulo) * modulo
    if new_h == h and new_w == w:
        return img
    padded = np.zeros((new_h, new_w, 3), dtype=img.dtype)
    padded[:h, :w] = img
    return padded


def get_image(img: np.ndarray) -> np.ndarray:
    """Prepare image for LaMa model."""
    if img.dtype != np.float32:
        img = img.astype(np.float32) / 255.0
    return img