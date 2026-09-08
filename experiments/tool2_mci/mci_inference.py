"""Reusable, application-independent inference wrapper for Change-Agent MCI."""

from __future__ import annotations

import gc
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch
from PIL import Image

from .vendor.change_agent_mci import VOCAB_PATH


MEAN = [0.39073 * 255, 0.38623 * 255, 0.32989 * 255]
STD = [0.15329 * 255, 0.14628 * 255, 0.13648 * 255]
CLASS_COLORS = np.asarray(
    [
        [0, 0, 0],
        [255, 255, 0],
        [255, 0, 0],
    ],
    dtype=np.uint8,
)
EXPECTED_CHECKPOINT_KEYS = {"encoder_dict", "encoder_trans_dict", "decoder_dict"}
EXPECTED_VOCAB_SIZE = 468


@dataclass(frozen=True)
class MCIPrediction:
    caption: str
    mask: np.ndarray
    inference_seconds: float


def load_model_classes() -> tuple[type, type, type]:
    from .vendor.change_agent_mci.model_decoder import DecoderTransformer
    from .vendor.change_agent_mci.model_encoder_att import AttentiveEncoder, Encoder

    return Encoder, AttentiveEncoder, DecoderTransformer


def load_and_validate_vocab(vocab_path: str | Path) -> dict[str, int]:
    path = Path(vocab_path).resolve()
    with path.open("r", encoding="utf-8") as stream:
        vocab = json.load(stream)
    if not isinstance(vocab, dict):
        raise ValueError(f"Vocabulary must be a JSON object: {path}")
    if len(vocab) != EXPECTED_VOCAB_SIZE:
        raise ValueError(
            f"Expected {EXPECTED_VOCAB_SIZE} vocabulary tokens, found {len(vocab)}"
        )
    ids = sorted(vocab.values())
    if ids != list(range(EXPECTED_VOCAB_SIZE)):
        raise ValueError("Vocabulary IDs must be exactly 0..467")
    for special in ("<NULL>", "<START>", "<END>"):
        if special not in vocab:
            raise ValueError(f"Vocabulary is missing required token {special}")
    return {str(token): int(token_id) for token, token_id in vocab.items()}


def preprocess_image(image_path: str | Path) -> torch.Tensor:
    path = Path(image_path).resolve()
    with Image.open(path) as image:
        if image.mode != "RGB":
            raise ValueError(f"MCI expects an RGB image, got mode {image.mode}: {path}")
        if image.size != (256, 256):
            raise ValueError(f"MCI Phase 1 expects 256x256 images, got {image.size}: {path}")
        array = np.asarray(image, dtype=np.float32).copy()

    chw = array.transpose(2, 0, 1)
    for channel in range(3):
        chw[channel] -= MEAN[channel]
        chw[channel] /= STD[channel]
    return torch.FloatTensor(chw).unsqueeze(0)


def decode_caption(sequence: Sequence[int], vocab: Mapping[str, int]) -> str:
    id_to_token = {int(token_id): token for token, token_id in vocab.items()}
    ignored = {vocab["<NULL>"], vocab["<START>"], vocab["<END>"]}
    tokens = [id_to_token[int(token_id)] for token_id in sequence if token_id not in ignored]
    return " ".join(tokens).strip()


def summarize_mask(mask: np.ndarray) -> dict[str, Any]:
    if mask.ndim != 2:
        raise ValueError(f"Expected a 2-D class mask, got shape {mask.shape}")
    unique, counts = np.unique(mask, return_counts=True)
    count_by_class = {str(class_id): 0 for class_id in range(3)}
    for class_id, count in zip(unique.tolist(), counts.tolist()):
        count_by_class[str(int(class_id))] = int(count)
    total = int(mask.size)
    changed = int(np.count_nonzero(mask))
    return {
        "mask_shape": [int(value) for value in mask.shape],
        "unique_classes": [int(value) for value in unique.tolist()],
        "changed_pixels": changed,
        "total_pixels": total,
        "changed_percent": changed * 100.0 / total,
        "class_pixel_counts": count_by_class,
    }


def visualize_mask(mask: np.ndarray) -> np.ndarray:
    if mask.ndim != 2 or np.any(mask < 0) or np.any(mask > 2):
        raise ValueError("Semantic mask must be 2-D and contain only classes 0, 1, and 2")
    return CLASS_COLORS[mask.astype(np.uint8)]


def create_overlay(image_b: np.ndarray, mask_rgb: np.ndarray, alpha: float = 0.45) -> np.ndarray:
    if image_b.shape != mask_rgb.shape or image_b.shape[-1] != 3:
        raise ValueError("Image B and RGB mask must have the same HxWx3 shape")
    result = image_b.astype(np.float32).copy()
    changed = np.any(mask_rgb != 0, axis=2)
    result[changed] = (
        (1.0 - alpha) * result[changed] + alpha * mask_rgb[changed].astype(np.float32)
    )
    return np.clip(result, 0, 255).astype(np.uint8)


def compute_binary_metrics(prediction: np.ndarray, ground_truth: np.ndarray) -> dict[str, float]:
    if prediction.shape != ground_truth.shape:
        raise ValueError("Prediction and ground truth must have matching shapes")
    predicted_changed = prediction != 0
    actual_changed = ground_truth != 0
    true_positive = int(np.count_nonzero(predicted_changed & actual_changed))
    false_positive = int(np.count_nonzero(predicted_changed & ~actual_changed))
    false_negative = int(np.count_nonzero(~predicted_changed & actual_changed))
    union = true_positive + false_positive + false_negative
    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    iou = true_positive / union if union else 1.0
    precision = true_positive / precision_denominator if precision_denominator else 0.0
    recall = true_positive / recall_denominator if recall_denominator else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "changed_iou": iou,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _state_dict_status(load_result: Any) -> dict[str, list[str]]:
    return {
        "missing_keys": list(load_result.missing_keys),
        "unexpected_keys": list(load_result.unexpected_keys),
    }


class MCIInference:
    """Load the original MCI architecture once and perform paired-image inference."""

    def __init__(
        self,
        checkpoint_path: str | Path,
        vocab_path: str | Path | None = None,
        device: str | torch.device | None = None,
    ) -> None:
        self.checkpoint_path = Path(checkpoint_path).resolve()
        self.vocab_path = Path(vocab_path if vocab_path is not None else VOCAB_PATH).resolve()
        if not self.checkpoint_path.is_file():
            raise FileNotFoundError(self.checkpoint_path)

        requested_device = torch.device(
            device if device is not None else ("cuda:0" if torch.cuda.is_available() else "cpu")
        )
        if requested_device.type == "cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available")
        self.device = requested_device
        self.word_vocab = load_and_validate_vocab(self.vocab_path)

        Encoder, AttentiveEncoder, DecoderTransformer = load_model_classes()

        self.encoder = Encoder("segformer-mit_b1")
        self.encoder_trans = AttentiveEncoder(
            train_stage=None,
            n_layers=3,
            feature_size=[16, 16, 512],
            heads=8,
            dropout=0.1,
        )
        self.decoder = DecoderTransformer(
            encoder_dim=512,
            feature_dim=512,
            vocab_size=len(self.word_vocab),
            max_lengths=41,
            word_vocab=self.word_vocab,
            n_head=8,
            n_layers=1,
            dropout=0.1,
        )

        checkpoint = torch.load(self.checkpoint_path, map_location=self.device)
        if not isinstance(checkpoint, dict):
            raise ValueError("MCI checkpoint must contain a dictionary")
        missing_sections = EXPECTED_CHECKPOINT_KEYS.difference(checkpoint)
        if missing_sections:
            raise ValueError(f"MCI checkpoint is missing sections: {sorted(missing_sections)}")

        self.load_status = {
            "encoder_dict": _state_dict_status(
                self.encoder.load_state_dict(checkpoint["encoder_dict"], strict=True)
            ),
            "encoder_trans_dict": _state_dict_status(
                self.encoder_trans.load_state_dict(
                    checkpoint["encoder_trans_dict"], strict=False
                )
            ),
            "decoder_dict": _state_dict_status(
                self.decoder.load_state_dict(checkpoint["decoder_dict"], strict=True)
            ),
        }
        del checkpoint
        gc.collect()
        if self.device.type == "cuda":
            torch.cuda.empty_cache()

        self.encoder.to(self.device).eval()
        self.encoder_trans.to(self.device).eval()
        self.decoder.to(self.device).eval()

    def predict(self, image_a_path: str | Path, image_b_path: str | Path) -> MCIPrediction:
        image_a = preprocess_image(image_a_path).to(self.device)
        image_b = preprocess_image(image_b_path).to(self.device)

        with torch.inference_mode():
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            started = time.perf_counter()
            features_a, features_b = self.encoder(image_a, image_b)
            caption_a, caption_b, segmentation_logits = self.encoder_trans(
                features_a, features_b
            )
            sequence = self.decoder.sample(caption_a, caption_b, k=1)
            mask = torch.argmax(segmentation_logits, dim=1)[0].to("cpu").numpy().astype(np.uint8)
            if self.device.type == "cuda":
                torch.cuda.synchronize(self.device)
            elapsed = time.perf_counter() - started

        return MCIPrediction(
            caption=decode_caption(sequence, self.word_vocab),
            mask=mask,
            inference_seconds=elapsed,
        )
