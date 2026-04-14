from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from cliplab_backend.config import settings
from cliplab_backend.inpaint import STTNInpaintError, STTNInpaintRuntime
from cliplab_backend.schemas import WatermarkRegion

MASK_EXPAND_PIXELS = 12
CHUNK_FRAME_COUNT = 80
TEMPORAL_BLEND_RADIUS = 2


def clamp_region(region: WatermarkRegion, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = max(0, min(width - 1, int(region.x * width)))
    y1 = max(0, min(height - 1, int(region.y * height)))
    x2 = max(x1 + 1, min(width, int((region.x + region.width) * width)))
    y2 = max(y1 + 1, min(height, int((region.y + region.height) * height)))
    return x1, y1, x2, y2


def batch_generator[T](data: list[T], max_batch_size: int):
    size = max(1, max_batch_size)
    total = len(data)
    index = 0
    while index < total:
        yield data[index : index + size]
        index += size


def create_mask(
    size: tuple[int, int],
    coords_list: list[tuple[int, int, int, int]],
    expand_pixels: int = MASK_EXPAND_PIXELS,
) -> np.ndarray:
    mask = np.zeros(size, dtype=np.uint8)
    for xmin, xmax, ymin, ymax in coords_list:
        x1 = max(0, xmin - expand_pixels)
        y1 = max(0, ymin - expand_pixels)
        x2 = min(size[1], xmax + expand_pixels)
        y2 = min(size[0], ymax + expand_pixels)
        cv2.rectangle(mask, (x1, y1), (x2, y2), 255, thickness=-1)
    return mask


def _align_span(start: int, end: int, limit: int, multiple: int) -> tuple[int, int]:
    if multiple <= 1:
        return start, end
    length = end - start
    remainder = length % multiple
    if remainder == 0:
        return start, end
    padding = multiple - remainder
    left_padding = padding // 2
    right_padding = padding - left_padding
    start = max(0, start - left_padding)
    end = min(limit, end + right_padding)
    length = end - start
    remainder = length % multiple
    if remainder == 0:
        return start, end
    if end + (multiple - remainder) <= limit:
        end += multiple - remainder
    elif start - (multiple - remainder) >= 0:
        start -= multiple - remainder
    return start, end


def get_inpaint_areas_by_mask(
    width: int,
    height: int,
    preferred_height: int,
    mask: np.ndarray,
    multiple: int = 2,
) -> list[tuple[int, int, int, int]]:
    if mask.ndim == 3:
        binary_mask = (mask[:, :, 0] > 0).astype(np.uint8) * 255
    else:
        binary_mask = (mask > 0).astype(np.uint8) * 255

    if np.all(binary_mask == 0):
        return []

    num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(binary_mask, connectivity=8)
    groups: list[list[dict[str, int]]] = []
    min_component_area = 16

    for label in range(1, num_labels):
        x = int(stats[label, cv2.CC_STAT_LEFT])
        y = int(stats[label, cv2.CC_STAT_TOP])
        component_width = int(stats[label, cv2.CC_STAT_WIDTH])
        component_height = int(stats[label, cv2.CC_STAT_HEIGHT])
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < min_component_area:
            continue

        component = {
            "x1": x,
            "x2": x + component_width,
            "y1": y,
            "y2": y + component_height,
            "center_y": int(centroids[label][1]),
        }

        merged = False
        for group in groups:
            group_x1 = min(item["x1"] for item in group)
            group_x2 = max(item["x2"] for item in group)
            group_y1 = min(item["y1"] for item in group)
            group_y2 = max(item["y2"] for item in group)
            candidate_y1 = min(group_y1, component["y1"])
            candidate_y2 = max(group_y2, component["y2"])
            x_gap = max(0, max(group_x1, component["x1"]) - min(group_x2, component["x2"]))
            y_gap = max(0, component["y1"] - group_y2, group_y1 - component["y2"])
            if candidate_y2 - candidate_y1 <= max(preferred_height, group_y2 - group_y1) and x_gap <= 48 and y_gap <= 24:
                group.append(component)
                merged = True
                break
        if not merged:
            groups.append([component])

    areas: list[tuple[int, int, int, int]] = []
    for group in groups:
        x1 = min(item["x1"] for item in group)
        x2 = max(item["x2"] for item in group)
        y1 = min(item["y1"] for item in group)
        y2 = max(item["y2"] for item in group)

        center_y = sum(item["center_y"] for item in group) // len(group)
        target_height = max(preferred_height, y2 - y1)
        ymin = max(0, center_y - target_height // 2)
        ymax = min(height, ymin + target_height)
        if ymax - ymin < target_height:
            ymin = max(0, ymax - target_height)

        xmin = max(0, x1 - MASK_EXPAND_PIXELS)
        xmax = min(width, x2 + MASK_EXPAND_PIXELS)
        ymin = max(0, ymin - MASK_EXPAND_PIXELS // 2)
        ymax = min(height, ymax + MASK_EXPAND_PIXELS // 2)

        ymin, ymax = _align_span(ymin, ymax, height, multiple)
        xmin, xmax = _align_span(xmin, xmax, width, multiple)
        area_tuple = (ymin, ymax, xmin, xmax)
        if area_tuple not in areas:
            areas.append(area_tuple)

    return areas


class WatermarkService:
    def __init__(self) -> None:
        self.supported_algorithms = {"sttn_auto", "lama"}
        self._sttn_runtime: STTNInpaintRuntime | None = None
        self._sttn_runtime_failed = False

    def ensure_models(self, algorithm: str) -> None:
        if algorithm not in self.supported_algorithms:
            raise ValueError(f"Unsupported algorithm: {algorithm}")

    def process(
        self,
        input_path: str,
        output_directory: str,
        region: WatermarkRegion,
        algorithm: str,
        progress_callback: Callable[[int], None],
    ) -> str:
        self.ensure_models(algorithm)
        source = Path(input_path)
        if not source.exists():
            raise FileNotFoundError(f"Input video does not exist: {input_path}")

        output_root = Path(output_directory)
        output_root.mkdir(parents=True, exist_ok=True)
        output_path = output_root / f"{source.stem}_clean.mp4"

        capture = cv2.VideoCapture(str(source))
        if not capture.isOpened():
            raise ValueError("无法读取输入视频。")

        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = max(1, int(capture.get(cv2.CAP_PROP_FRAME_COUNT)))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

        selected = clamp_region(region, width, height)
        mask = create_mask((height, width), [(selected[0], selected[2], selected[1], selected[3])])
        preferred_height = max(selected[3] - selected[1] + MASK_EXPAND_PIXELS * 2, int(width * 3 / 16))
        inpaint_areas = get_inpaint_areas_by_mask(width, height, preferred_height, mask, multiple=2)
        if not inpaint_areas:
            inpaint_areas = [(selected[1], selected[3], selected[0], selected[2])]

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_video:
            temp_path = Path(temp_video.name)

        writer = cv2.VideoWriter(
            str(temp_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            capture.release()
            raise ValueError("无法创建输出视频。")

        processed = 0
        progress_callback(4)
        try:
            while True:
                chunk_frames = self._read_chunk(capture)
                if not chunk_frames:
                    break
                repaired_frames = self._repair_chunk(chunk_frames, inpaint_areas, mask, algorithm)
                for frame in repaired_frames:
                    writer.write(frame)
                    processed += 1
                    progress_callback(min(96, max(5, int(processed / frame_count * 100))))
        finally:
            capture.release()
            writer.release()

        self._merge_audio(source, temp_path, output_path)
        temp_path.unlink(missing_ok=True)
        progress_callback(100)
        return str(output_path)

    def _read_chunk(self, capture: cv2.VideoCapture) -> list[np.ndarray]:
        frames: list[np.ndarray] = []
        for _ in range(CHUNK_FRAME_COUNT):
            ok, frame = capture.read()
            if not ok:
                break
            frames.append(frame)
        return frames

    def _repair_chunk(
        self,
        frames: list[np.ndarray],
        inpaint_areas: list[tuple[int, int, int, int]],
        mask: np.ndarray,
        algorithm: str,
    ) -> list[np.ndarray]:
        repaired_frames = [frame.copy() for frame in frames]
        for ymin, ymax, xmin, xmax in inpaint_areas:
            local_mask = mask[ymin:ymax, xmin:xmax]
            if np.count_nonzero(local_mask) == 0:
                continue
            crops = [frame[ymin:ymax, xmin:xmax].copy() for frame in repaired_frames]
            repaired_crops = self._run_region_inpaint(crops, local_mask, algorithm)
            alpha = self._build_blend_alpha(local_mask)
            for index, crop in enumerate(repaired_crops):
                target = repaired_frames[index][ymin:ymax, xmin:xmax].astype(np.float32)
                blended = crop.astype(np.float32) * alpha + target * (1.0 - alpha)
                repaired_frames[index][ymin:ymax, xmin:xmax] = np.clip(blended, 0, 255).astype(np.uint8)
        return repaired_frames

    def _run_region_inpaint(
        self,
        crops: list[np.ndarray],
        local_mask: np.ndarray,
        algorithm: str,
    ) -> list[np.ndarray]:
        if algorithm == "sttn_auto":
            sttn_runtime = self._get_sttn_runtime()
            if sttn_runtime is not None:
                return sttn_runtime.inpaint(crops, local_mask)

        radius = 5 if algorithm == "lama" else 3
        repaired = [cv2.inpaint(crop, local_mask, radius, cv2.INPAINT_TELEA) for crop in crops]
        if algorithm == "sttn_auto" and len(repaired) > 1:
            repaired = self._temporal_stabilize(repaired, local_mask)
        return repaired

    def _get_sttn_runtime(self) -> STTNInpaintRuntime | None:
        if self._sttn_runtime_failed:
            return None
        if self._sttn_runtime is not None:
            return self._sttn_runtime
        model_path = settings.models_dir / "sttn_auto.pth"
        try:
            self._sttn_runtime = STTNInpaintRuntime(model_path)
        except STTNInpaintError:
            self._sttn_runtime_failed = True
            self._sttn_runtime = None
        return self._sttn_runtime

    def _temporal_stabilize(self, crops: list[np.ndarray], local_mask: np.ndarray) -> list[np.ndarray]:
        mask_bool = local_mask > 0
        stabilized: list[np.ndarray] = []
        for index, crop in enumerate(crops):
            start = max(0, index - TEMPORAL_BLEND_RADIUS)
            end = min(len(crops), index + TEMPORAL_BLEND_RADIUS + 1)
            window = np.stack(crops[start:end]).astype(np.float32)
            temporal_reference = np.median(window, axis=0)
            current = crop.astype(np.float32)
            blended = current.copy()
            blended[mask_bool] = current[mask_bool] * 0.72 + temporal_reference[mask_bool] * 0.28
            stabilized.append(np.clip(blended, 0, 255).astype(np.uint8))
        return stabilized

    def _build_blend_alpha(self, local_mask: np.ndarray) -> np.ndarray:
        blurred = cv2.GaussianBlur(local_mask, (0, 0), sigmaX=2.4)
        alpha = (blurred.astype(np.float32) / 255.0)[:, :, None]
        return np.repeat(alpha, 3, axis=2)

    def _merge_audio(self, source: Path, video_without_audio: Path, output_path: Path) -> None:
        command = [
            settings.ffmpeg_path,
            "-y",
            "-i",
            str(video_without_audio),
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except Exception:
            shutil.copy2(video_without_audio, output_path)
