from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


class STTNInpaintError(RuntimeError):
    pass


@dataclass(frozen=True)
class STTNConfig:
    model_input_width: int = 640
    model_input_height: int = 120
    neighbor_stride: int = 5
    reference_length: int = 10


class STTNInpaintRuntime:
    def __init__(self, model_path: Path, config: STTNConfig | None = None) -> None:
        self.config = config or STTNConfig()
        self.model_path = model_path
        self.torch = self._import_torch()
        self.device = self._select_device()
        self.model = self._build_model()
        self._load_weights()
        self.model.eval()

    @staticmethod
    def _import_torch():
        try:
            import torch
            import torch.nn as nn
            import torch.nn.functional as F
        except Exception as error:  # pragma: no cover - depends on host environment
            raise STTNInpaintError(
                "STTN 运行需要安装 torch/torchvision。可执行 uv sync --project backend --extra sttn。"
            ) from error
        return {"torch": torch, "nn": nn, "F": F}

    def _select_device(self):
        torch = self.torch["torch"]
        if torch.cuda.is_available():
            return torch.device("cuda")
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    def _build_model(self):
        torch = self.torch["torch"]
        nn = self.torch["nn"]
        F = self.torch["F"]

        class BaseNetwork(nn.Module):
            def __init__(self):
                super().__init__()

        class Deconv(nn.Module):
            def __init__(self, input_channel: int, output_channel: int, kernel_size: int = 3, padding: int = 0):
                super().__init__()
                self.conv = nn.Conv2d(input_channel, output_channel, kernel_size=kernel_size, stride=1, padding=padding)

            def forward(self, x):
                x = F.interpolate(x, scale_factor=2, mode="bilinear", align_corners=True)
                return self.conv(x)

        class Attention(nn.Module):
            def forward(self, query, key, value):
                scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(query.size(-1))
                p_attn = F.softmax(scores, dim=-1)
                return torch.matmul(p_attn, value), p_attn

        class MultiHeadedAttention(nn.Module):
            def __init__(self, patchsize, d_model):
                super().__init__()
                self.patchsize = patchsize
                self.query_embedding = nn.Conv2d(d_model, d_model, kernel_size=1, padding=0)
                self.value_embedding = nn.Conv2d(d_model, d_model, kernel_size=1, padding=0)
                self.key_embedding = nn.Conv2d(d_model, d_model, kernel_size=1, padding=0)
                self.output_linear = nn.Sequential(
                    nn.Conv2d(d_model, d_model, kernel_size=3, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                )
                self.attention = Attention()

            def forward(self, x, b, c):
                bt, _, h, w = x.size()
                t = bt // b
                d_k = c // len(self.patchsize)
                output = []
                _query = self.query_embedding(x)
                _key = self.key_embedding(x)
                _value = self.value_embedding(x)

                for (width, height), query, key, value in zip(
                    self.patchsize,
                    torch.chunk(_query, len(self.patchsize), dim=1),
                    torch.chunk(_key, len(self.patchsize), dim=1),
                    torch.chunk(_value, len(self.patchsize), dim=1),
                ):
                    out_w, out_h = w // width, h // height
                    query = query.view(b, t, d_k, out_h, height, out_w, width)
                    query = query.permute(0, 1, 3, 5, 2, 4, 6).contiguous().view(
                        b, t * out_h * out_w, d_k * height * width
                    )
                    key = key.view(b, t, d_k, out_h, height, out_w, width)
                    key = key.permute(0, 1, 3, 5, 2, 4, 6).contiguous().view(
                        b, t * out_h * out_w, d_k * height * width
                    )
                    value = value.view(b, t, d_k, out_h, height, out_w, width)
                    value = value.permute(0, 1, 3, 5, 2, 4, 6).contiguous().view(
                        b, t * out_h * out_w, d_k * height * width
                    )
                    y, _ = self.attention(query, key, value)
                    y = y.view(b, t, out_h, out_w, d_k, height, width)
                    y = y.permute(0, 1, 4, 2, 5, 3, 6).contiguous().view(bt, d_k, h, w)
                    output.append(y)

                output = torch.cat(output, 1)
                return self.output_linear(output)

        class FeedForward(nn.Module):
            def __init__(self, d_model):
                super().__init__()
                self.conv = nn.Sequential(
                    nn.Conv2d(d_model, d_model, kernel_size=3, padding=2, dilation=2),
                    nn.LeakyReLU(0.2, inplace=True),
                    nn.Conv2d(d_model, d_model, kernel_size=3, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                )

            def forward(self, x):
                return self.conv(x)

        class TransformerBlock(nn.Module):
            def __init__(self, patchsize, hidden=128):
                super().__init__()
                self.attention = MultiHeadedAttention(patchsize, d_model=hidden)
                self.feed_forward = FeedForward(hidden)

            def forward(self, x):
                tensor, batch_size, channels = x["x"], x["b"], x["c"]
                tensor = tensor + self.attention(tensor, batch_size, channels)
                tensor = tensor + self.feed_forward(tensor)
                return {"x": tensor, "b": batch_size, "c": channels}

        class InpaintGenerator(BaseNetwork):
            def __init__(self):
                super().__init__()
                channel = 256
                stack_num = 8
                patchsize = [(80, 15), (32, 6), (10, 5), (5, 3)]
                blocks = [TransformerBlock(patchsize, hidden=channel) for _ in range(stack_num)]
                self.transformer = nn.Sequential(*blocks)
                self.encoder = nn.Sequential(
                    nn.Conv2d(3, 64, kernel_size=3, stride=2, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                    nn.Conv2d(64, 64, kernel_size=3, stride=1, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                    nn.Conv2d(64, 128, kernel_size=3, stride=2, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                    nn.Conv2d(128, channel, kernel_size=3, stride=1, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                )
                self.decoder = nn.Sequential(
                    Deconv(channel, 128, kernel_size=3, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                    nn.Conv2d(128, 64, kernel_size=3, stride=1, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                    Deconv(64, 64, kernel_size=3, padding=1),
                    nn.LeakyReLU(0.2, inplace=True),
                    nn.Conv2d(64, 3, kernel_size=3, stride=1, padding=1),
                )

            def infer(self, feat):
                t, c, _, _ = feat.size()
                return self.transformer({"x": feat, "b": 1, "c": c})["x"]

        return InpaintGenerator().to(self.device)

    def _load_weights(self) -> None:
        torch = self.torch["torch"]
        if not self.model_path.exists():
            raise STTNInpaintError(
                f"未找到 STTN 模型文件：{self.model_path}。请先配置并下载 CLIPLAB_STTN_AUTO_MODEL_URL 对应权重。"
            )
        checkpoint = torch.load(self.model_path, map_location="cpu")
        state_dict = checkpoint.get("netG", checkpoint)
        self.model.load_state_dict(state_dict, strict=True)

    def _frames_to_tensor(self, frames: list[np.ndarray]):
        torch = self.torch["torch"]
        rgb_frames = [cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) for frame in frames]
        stacked = np.stack(rgb_frames, axis=2)
        tensor = torch.from_numpy(stacked).permute(2, 3, 0, 1).contiguous().float().div(255.0)
        return tensor

    def _get_ref_index(self, neighbor_ids: list[int], length: int) -> list[int]:
        references: list[int] = []
        for index in range(0, length, self.config.reference_length):
            if index not in neighbor_ids:
                references.append(index)
        return references

    def _infer_scaled(self, scaled_frames: list[np.ndarray]) -> list[np.ndarray]:
        torch = self.torch["torch"]
        feats = self._frames_to_tensor(scaled_frames).unsqueeze(0) * 2 - 1
        frame_length = len(scaled_frames)
        feats = feats.to(self.device)
        comp_frames: list[np.ndarray | None] = [None] * frame_length
        with torch.no_grad():
            feats = self.model.encoder(
                feats.view(frame_length, 3, self.config.model_input_height, self.config.model_input_width)
            )
            _, channels, feat_h, feat_w = feats.size()
            feats = feats.view(1, frame_length, channels, feat_h, feat_w)
            for frame_index in range(0, frame_length, self.config.neighbor_stride):
                neighbor_ids = [
                    idx
                    for idx in range(
                        max(0, frame_index - self.config.neighbor_stride),
                        min(frame_length, frame_index + self.config.neighbor_stride + 1),
                    )
                ]
                ref_ids = self._get_ref_index(neighbor_ids, frame_length)
                pred_feat = self.model.infer(feats[0, neighbor_ids + ref_ids, :, :, :])
                pred_img = torch.tanh(self.model.decoder(pred_feat[: len(neighbor_ids), :, :, :]))
                pred_img = (pred_img + 1) / 2
                pred_img = pred_img.cpu().permute(0, 2, 3, 1).numpy() * 255
                for neighbor_offset, idx in enumerate(neighbor_ids):
                    img = pred_img[neighbor_offset].astype(np.uint8)
                    if comp_frames[idx] is None:
                        comp_frames[idx] = img
                    else:
                        comp_frames[idx] = (
                            comp_frames[idx].astype(np.float32) * 0.5 + img.astype(np.float32) * 0.5
                        ).astype(np.uint8)
        return [frame if frame is not None else scaled_frames[idx] for idx, frame in enumerate(comp_frames)]

    def inpaint(self, crops: list[np.ndarray], local_mask: np.ndarray) -> list[np.ndarray]:
        if not crops:
            return []
        scaled_frames = [
            cv2.resize(frame, (self.config.model_input_width, self.config.model_input_height)) for frame in crops
        ]
        completed = self._infer_scaled(scaled_frames)
        binary_mask = (local_mask > 0).astype(np.float32)[:, :, None]
        result: list[np.ndarray] = []
        for crop, completed_frame in zip(crops, completed):
            resized = cv2.resize(completed_frame, (crop.shape[1], crop.shape[0]))
            resized = cv2.cvtColor(resized.astype(np.uint8), cv2.COLOR_RGB2BGR).astype(np.float32)
            original = crop.astype(np.float32)
            blended = resized * binary_mask + original * (1.0 - binary_mask)
            result.append(np.clip(blended, 0, 255).astype(np.uint8))
        return result
