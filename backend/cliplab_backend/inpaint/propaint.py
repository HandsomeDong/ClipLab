from __future__ import annotations

import gc
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


class ProPainterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProPainterConfig:
    sub_video_length: int = 80
    neighbor_length: int = 10
    mask_dilation: int = 4
    ref_stride: int = 10
    raft_iter: int = 20
    use_fp16: bool = True


class ProPainterInpaintRuntime:
    def __init__(self, model_dir: Path, config: ProPainterConfig | None = None) -> None:
        self.config = config or ProPainterConfig()
        self.model_dir = model_dir
        self.torch = self._import_torch()
        self.device = self._select_device()
        self.use_half = self.config.use_fp16 and self.device.type != "cpu"
        self._raft_model = None
        self._flow_complete_model = None
        self._inpaint_model = None

    @staticmethod
    def _import_torch():
        try:
            import torch
        except Exception as error:
            raise ProPainterError(
                "ProPainter 运行需要安装 torch/torchvision。可执行 uv sync --project backend --extra sttn。"
            ) from error
        return {"torch": torch}

    def _select_device(self):
        torch = self.torch["torch"]
        if torch.cuda.is_available():
            return torch.device("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    def _init_raft_model(self):
        import torch.nn as nn
        from backend.inpaint.video.model.modules.flow_comp_raft import RAFT_bi

        torch = self.torch["torch"]
        raft_path = self.model_dir / "raft-things.pth"
        if not raft_path.exists():
            raise ProPainterError(f"未找到 RAFT 模型文件：{raft_path}")
        self._raft_model = RAFT_bi(str(raft_path), self.device)
        for p in self._raft_model.parameters():
            p.requires_grad = False
        self._raft_model.eval()

    def _init_flow_complete_model(self):
        import torch.nn as nn
        from backend.inpaint.video.model.recurrent_flow_completion import RecurrentFlowCompleteNet

        torch = self.torch["torch"]
        flow_path = self.model_dir / "recurrent_flow_completion.pth"
        if not flow_path.exists():
            raise ProPainterError(f"未找到 Flow Complete 模型文件：{flow_path}")
        self._flow_complete_model = RecurrentFlowCompleteNet(str(flow_path))
        for p in self._flow_complete_model.parameters():
            p.requires_grad = False
        if self.use_half:
            self._flow_complete_model = self._flow_complete_model.half()
        self._flow_complete_model = self._flow_complete_model.to(self.device)
        self._flow_complete_model.eval()

    def _init_inpaint_model(self):
        import torch.nn as nn
        from backend.inpaint.video.model.propainter import InpaintGenerator

        torch = self.torch["torch"]
        model_path = self.model_dir / "ProPainter.pth"
        if not model_path.exists():
            raise ProPainterError(f"未找到 ProPainter 模型文件：{model_path}")
        self._inpaint_model = InpaintGenerator(model_path=str(model_path))
        if self.use_half:
            self._inpaint_model = self._inpaint_model.half()
        self._inpaint_model = self._inpaint_model.to(self.device).eval()

    def ensure_models(self):
        if self._raft_model is None:
            self._init_raft_model()
        if self._flow_complete_model is None:
            self._init_flow_complete_model()
        if self._inpaint_model is None:
            self._init_inpaint_model()

    @staticmethod
    def _read_mask(mask: np.ndarray, length: int, flow_dilation: int = 8, mask_dilation: int = 5):
        """Read and dilate mask for flow and inpainting."""
        if mask.ndim == 3:
            if mask.shape[2] == 1:
                mask = mask.squeeze(2)
            elif mask.shape[2] == 3:
                mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)

        mask_img = Image.fromarray(mask) if not isinstance(mask, Image.Image) else mask

        # Dilate for flow
        if flow_dilation > 0:
            flow_mask_img = scipy_ndimage_binary_dilation(np.array(mask_img), iterations=flow_dilation).astype(np.uint8)
        else:
            flow_mask_img = (np.array(mask_img) > 0.1).astype(np.uint8)

        # Dilate for inpaint
        if mask_dilation > 0:
            dilated = scipy_ndimage_binary_dilation(np.array(mask_img), iterations=mask_dilation).astype(np.uint8)
        else:
            dilated = (np.array(mask_img) > 0.1).astype(np.uint8)

        # Convert back to PIL for tensor conversion
        flow_mask = Image.fromarray(flow_mask_img * 255)
        dilated_mask = Image.fromarray(dilated * 255)

        # Duplicate for all frames if single mask
        if length > 1:
            flow_masks = [flow_mask] * length
            masks_dilated = [dilated_mask] * length
        else:
            flow_masks = [flow_mask]
            masks_dilated = [dilated_mask]

        return flow_masks, masks_dilated

    def _to_tensors(self):
        try:
            from backend.inpaint.video.core.utils import to_tensors
            return to_tensors()
        except ImportError:
            from torchvision import transforms
            return transforms.Compose([
                transforms.ToTensor(),
            ])

    def _get_ref_index(self, mid_neighbor_id: int, neighbor_ids: list[int], length: int, ref_stride: int = 10, ref_num: int = -1):
        ref_index = []
        if ref_num == -1:
            for i in range(0, length, ref_stride):
                if i not in neighbor_ids:
                    ref_index.append(i)
        else:
            start_idx = max(0, mid_neighbor_id - ref_stride * (ref_num // 2))
            end_idx = min(length, mid_neighbor_id + ref_stride * (ref_num // 2))
            for i in range(start_idx, end_idx, ref_stride):
                if i not in neighbor_ids:
                    if len(ref_index) > ref_num:
                        break
                    ref_index.append(i)
        return ref_index

    def inpaint(self, frames: list[np.ndarray], mask: np.ndarray) -> list[np.ndarray]:
        """Process frames with ProPainter algorithm."""
        self.ensure_models()
        torch = self.torch["torch"]

        # Convert frames to PIL images
        frames_pil = [Image.fromarray(cv2.cvtColor(f, cv2.COLOR_BGR2RGB)) for f in frames]
        size = frames_pil[0].size
        frames_len = len(frames)

        flow_masks, masks_dilated = self._read_mask(mask, frames_len, self.config.mask_dilation, self.config.mask_dilation)

        # Prepare tensors
        to_tensor = self._to_tensors()
        frames_tensor = to_tensor(frames_pil).unsqueeze(0) * 2 - 1
        flow_masks_tensor = to_tensor(flow_masks).unsqueeze(0)
        masks_dilated_tensor = to_tensor(masks_dilated).unsqueeze(0)

        frames_tensor = frames_tensor.to(self.device)
        flow_masks_tensor = flow_masks_tensor.to(self.device)
        masks_dilated_tensor = masks_dilated_tensor.to(self.device)

        video_length = frames_tensor.size(1)

        with torch.no_grad():
            # Determine short clip length based on resolution
            if frames_tensor.size(-1) <= 640:
                short_clip_len = 12
            elif frames_tensor.size(-1) <= 720:
                short_clip_len = 8
            elif frames_tensor.size(-1) <= 1280:
                short_clip_len = 4
            else:
                short_clip_len = 2

            # Compute flow with RAFT
            if frames_tensor.size(1) > short_clip_len:
                gt_flows_f_list, gt_flows_b_list = [], []
                for f in range(0, video_length, short_clip_len):
                    end_f = min(video_length, f + short_clip_len)
                    if f == 0:
                        flows_f, flows_b = self._raft_model(frames_tensor[:, f:end_f], iters=self.config.raft_iter)
                    else:
                        flows_f, flows_b = self._raft_model(frames_tensor[:, f - 1:end_f], iters=self.config.raft_iter)
                    gt_flows_f_list.append(flows_f)
                    gt_flows_b_list.append(flows_b)
                    torch.cuda.empty_cache()
                gt_flows_f = torch.cat(gt_flows_f_list, dim=1)
                gt_flows_b = torch.cat(gt_flows_b_list, dim=1)
                gt_flows_bi = (gt_flows_f, gt_flows_b)
            else:
                gt_flows_bi = self._raft_model(frames_tensor, iters=self.config.raft_iter)
                torch.cuda.empty_cache()

            if self.use_half:
                frames_tensor = frames_tensor.half()
                flow_masks_tensor = flow_masks_tensor.half()
                masks_dilated_tensor = masks_dilated_tensor.half()
                gt_flows_bi = (gt_flows_bi[0].half(), gt_flows_bi[1].half())

            # Complete flow
            flow_length = gt_flows_bi[0].size(1)
            if flow_length > self.config.sub_video_length:
                pred_flows_f, pred_flows_b = [], []
                pad_len = 5
                for f in range(0, flow_length, self.config.sub_video_length):
                    s_f = max(0, f - pad_len)
                    e_f = min(flow_length, f + self.config.sub_video_length + pad_len)
                    pad_len_s = max(0, f) - s_f
                    pad_len_e = e_f - min(flow_length, f + self.config.sub_video_length)
                    pred_flows_bi_sub, _ = self._flow_complete_model.forward_bidirect_flow(
                        (gt_flows_bi[0][:, s_f:e_f], gt_flows_bi[1][:, s_f:e_f]),
                        flow_masks_tensor[:, s_f:e_f + 1])
                    pred_flows_bi_sub = self._flow_complete_model.combine_flow(
                        (gt_flows_bi[0][:, s_f:e_f], gt_flows_bi[1][:, s_f:e_f]),
                        pred_flows_bi_sub,
                        flow_masks_tensor[:, s_f:e_f + 1])
                    pred_flows_f.append(pred_flows_bi_sub[0][:, pad_len_s:e_f - s_f - pad_len_e])
                    pred_flows_b.append(pred_flows_bi_sub[1][:, pad_len_s:e_f - s_f - pad_len_e])
                    torch.cuda.empty_cache()
                pred_flows_f = torch.cat(pred_flows_f, dim=1)
                pred_flows_b = torch.cat(pred_flows_b, dim=1)
                pred_flows_bi = (pred_flows_f, pred_flows_b)
            else:
                pred_flows_bi, _ = self._flow_complete_model.forward_bidirect_flow(gt_flows_bi, flow_masks_tensor)
                pred_flows_bi = self._flow_complete_model.combine_flow(gt_flows_bi, pred_flows_bi, flow_masks_tensor)
                torch.cuda.empty_cache()

            # Image propagation
            masked_frames = frames_tensor * (1 - masks_dilated_tensor)
            subvideo_length_img_prop = min(100, self.config.sub_video_length)
            if video_length > subvideo_length_img_prop:
                updated_frames, updated_masks = [], []
                pad_len = 10
                h, w = frames_tensor.size(3), frames_tensor.size(4)
                for f in range(0, video_length, subvideo_length_img_prop):
                    s_f = max(0, f - pad_len)
                    e_f = min(video_length, f + subvideo_length_img_prop + pad_len)
                    pad_len_s = max(0, f) - s_f
                    pad_len_e = e_f - min(video_length, f + subvideo_length_img_prop)
                    b, t, _, _, _ = masks_dilated_tensor[:, s_f:e_f].size()
                    pred_flows_bi_sub = (pred_flows_bi[0][:, s_f:e_f - 1], pred_flows_bi[1][:, s_f:e_f - 1])
                    prop_imgs_sub, updated_local_masks_sub = self._inpaint_model.img_propagation(
                        masked_frames[:, s_f:e_f], pred_flows_bi_sub, masks_dilated_tensor[:, s_f:e_f], 'nearest')
                    updated_frames_sub = frames_tensor[:, s_f:e_f] * (1 - masks_dilated_tensor[:, s_f:e_f]) + prop_imgs_sub.view(b, t, 3, h, w) * masks_dilated_tensor[:, s_f:e_f]
                    updated_masks_sub = updated_local_masks_sub.view(b, t, 1, h, w)
                    updated_frames.append(updated_frames_sub[:, pad_len_s:e_f - s_f - pad_len_e])
                    updated_masks.append(updated_masks_sub[:, pad_len_s:e_f - s_f - pad_len_e])
                    torch.cuda.empty_cache()
                updated_frames = torch.cat(updated_frames, dim=1)
                updated_masks = torch.cat(updated_masks, dim=1)
            else:
                b, t, _, h, w = masks_dilated_tensor.size()
                prop_imgs, updated_local_masks = self._inpaint_model.img_propagation(
                    masked_frames, pred_flows_bi, masks_dilated_tensor, 'nearest')
                updated_frames = frames_tensor * (1 - masks_dilated_tensor) + prop_imgs.view(b, t, 3, h, w) * masks_dilated_tensor
                updated_masks = updated_local_masks.view(b, t, 1, h, w)
                torch.cuda.empty_cache()

        ori_frames = [np.array(f) for f in frames_pil]
        comp_frames = [None] * video_length
        neighbor_stride = self.config.neighbor_length // 2

        if video_length > self.config.sub_video_length:
            ref_num = self.config.sub_video_length // self.config.ref_stride
        else:
            ref_num = -1

        # Feature propagation + transformer
        for f in range(0, video_length, neighbor_stride):
            neighbor_ids = [i for i in range(max(0, f - neighbor_stride), min(video_length, f + neighbor_stride + 1))]
            ref_ids = self._get_ref_index(f, neighbor_ids, video_length, self.config.ref_stride, ref_num)
            selected_imgs = updated_frames[:, neighbor_ids + ref_ids, :, :, :]
            selected_masks = masks_dilated_tensor[:, neighbor_ids + ref_ids, :, :, :]
            selected_update_masks = updated_masks[:, neighbor_ids + ref_ids, :, :, :]
            selected_pred_flows_bi = (pred_flows_bi[0][:, neighbor_ids[:-1], :, :, :], pred_flows_bi[1][:, neighbor_ids[:-1], :, :, :])

            with torch.no_grad():
                l_t = len(neighbor_ids)
                pred_img = self._inpaint_model(selected_imgs, selected_pred_flows_bi, selected_masks, selected_update_masks, l_t)
                pred_img = pred_img.view(-1, 3, h, w)
                pred_img = (pred_img + 1) / 2
                pred_img = pred_img.cpu().permute(0, 2, 3, 1).numpy() * 255
                binary_masks = masks_dilated_tensor[0, neighbor_ids, :, :, :].cpu().permute(0, 2, 3, 1).numpy().astype(np.uint8)
                for i in range(len(neighbor_ids)):
                    idx = neighbor_ids[i]
                    img = np.array(pred_img[i]).astype(np.uint8) * binary_masks[i] + ori_frames[idx] * (1 - binary_masks[i])
                    if comp_frames[idx] is None:
                        comp_frames[idx] = img
                    else:
                        comp_frames[idx] = comp_frames[idx].astype(np.float32) * 0.5 + img.astype(np.float32) * 0.5
                    comp_frames[idx] = comp_frames[idx].astype(np.uint8)
            torch.cuda.empty_cache()

        # Convert back to BGR
        comp_frames = [cv2.cvtColor(i, cv2.COLOR_RGB2BGR) for i in comp_frames]
        return comp_frames


def scipy_ndimage_binary_dilation(a, iterations=1):
    """Binary dilation using scipy or cv2 fallback."""
    try:
        import scipy.ndimage
        return scipy.ndimage.binary_dilation(a, iterations=iterations)
    except ImportError:
        # Fallback to cv2
        kernel = np.ones((3, 3), np.uint8)
        return cv2.dilate(a, kernel, iterations=iterations)


try:
    from PIL import Image
except ImportError:
    Image = None