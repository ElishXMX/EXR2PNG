from __future__ import annotations

import json
import os
import binascii
import struct
import zlib
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


IMAGE_EXTS = {".png", ".jpg", ".jpeg"}
EXR_EXTS = {".exr"}


def _ensure_hwc(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr[:, :, None]
    if arr.ndim != 3:
        raise ValueError(f"Expected HWC image array, got shape {arr.shape}")
    return arr


def _bgr_to_rgb_if_needed(arr: np.ndarray, channel_order: str) -> np.ndarray:
    arr = _ensure_hwc(arr)
    if arr.shape[2] >= 3 and channel_order.upper() == "BGR":
        idx = [2, 1, 0] + list(range(3, arr.shape[2]))
        return arr[:, :, idx]
    if channel_order.upper() != "RGB":
        raise ValueError(f"Unsupported channel_order {channel_order!r}; use RGB or BGR")
    return arr


def read_exr(path: str | Path, channel_order: str = "RGB") -> np.ndarray:
    path = str(path)
    os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
    errors: list[str] = []

    try:
        import OpenEXR  # type: ignore
        import Imath  # type: ignore

        exr = OpenEXR.InputFile(path)
        header = exr.header()
        dw = header["dataWindow"]
        width = dw.max.x - dw.min.x + 1
        height = dw.max.y - dw.min.y + 1
        channels = list(header["channels"].keys())
        preferred = [c for c in ("R", "G", "B", "A") if c in channels]
        if len(preferred) < 3:
            preferred = channels[: min(4, len(channels))]
        pixel_type = Imath.PixelType(Imath.PixelType.FLOAT)
        planes = [
            np.frombuffer(exr.channel(c, pixel_type), dtype=np.float32).reshape(height, width)
            for c in preferred
        ]
        arr = np.stack(planes, axis=-1)
        return _bgr_to_rgb_if_needed(arr.astype(np.float32, copy=False), channel_order)
    except Exception as exc:  # pragma: no cover - depends on optional backend
        errors.append(f"OpenEXR: {exc}")

    try:
        import cv2  # type: ignore

        arr = cv2.imread(path, cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise ValueError("cv2.imread returned None")
        return _bgr_to_rgb_if_needed(arr.astype(np.float32, copy=False), "BGR")
    except Exception as exc:  # pragma: no cover - depends on optional backend
        errors.append(f"OpenCV: {exc}")

    try:
        import imageio.v3 as iio

        arr = iio.imread(path)
        return _bgr_to_rgb_if_needed(arr.astype(np.float32, copy=False), channel_order)
    except Exception as exc:  # pragma: no cover - depends on optional backend
        errors.append(f"imageio: {exc}")

    raise RuntimeError("Could not read EXR. Install OpenEXR or opencv-python. Tried: " + " | ".join(errors))


def write_exr(path: str | Path, arr_float32: np.ndarray, channel_order: str = "RGB") -> None:
    path = str(path)
    arr = _bgr_to_rgb_if_needed(np.asarray(arr_float32, dtype=np.float32), channel_order)
    arr = _ensure_hwc(arr)
    if arr.shape[2] == 3:
        alpha = np.ones(arr.shape[:2] + (1,), dtype=np.float32)
        arr = np.concatenate([arr, alpha], axis=2)
    errors: list[str] = []

    try:
        import OpenEXR  # type: ignore
        import Imath  # type: ignore

        h, w, c = arr.shape
        header = OpenEXR.Header(w, h)
        names = ["R", "G", "B", "A"][:c]
        header["channels"] = {name: Imath.Channel(Imath.PixelType(Imath.PixelType.FLOAT)) for name in names}
        out = OpenEXR.OutputFile(path, header)
        out.writePixels({name: arr[:, :, i].astype(np.float32).tobytes() for i, name in enumerate(names)})
        out.close()
        return
    except Exception as exc:  # pragma: no cover
        errors.append(f"OpenEXR: {exc}")

    try:
        import cv2  # type: ignore

        bgr = arr[:, :, [2, 1, 0, 3] if arr.shape[2] >= 4 else [2, 1, 0]]
        if cv2.imwrite(path, bgr.astype(np.float32)):
            return
        raise ValueError("cv2.imwrite returned false")
    except Exception as exc:  # pragma: no cover
        errors.append(f"OpenCV: {exc}")

    try:
        import imageio.v3 as iio

        iio.imwrite(path, arr.astype(np.float32))
        return
    except Exception as exc:  # pragma: no cover
        errors.append(f"imageio: {exc}")

    raise RuntimeError("Could not write EXR. Install OpenEXR or opencv-python. Tried: " + " | ".join(errors))


def read_png_or_jpg(path: str | Path) -> np.ndarray:
    path = Path(path)
    if path.suffix.lower() == ".png":
        png16 = _try_read_png16_rgb(path)
        if png16 is not None:
            return png16
    img = Image.open(path)
    arr = np.asarray(img)
    arr = _ensure_hwc(arr)
    if arr.shape[2] > 3:
        arr = arr[:, :, :3]
    if arr.dtype == np.uint16:
        rgb = arr.astype(np.float32) / 65535.0
    elif arr.dtype == np.uint8:
        rgb = arr.astype(np.float32) / 255.0
    else:
        rgb = arr.astype(np.float32)
        if rgb.max(initial=0.0) > 1.5:
            rgb /= np.iinfo(arr.dtype).max if np.issubdtype(arr.dtype, np.integer) else rgb.max()
    return np.clip(rgb[:, :, :3], 0.0, 1.0).astype(np.float32)


def write_png16(path: str | Path, rgb_float01: np.ndarray) -> None:
    arr = np.rint(np.clip(rgb_float01[:, :, :3], 0.0, 1.0) * 65535.0).astype(np.uint16)
    _write_png16_rgb(path, arr)


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def _write_png16_rgb(path: str | Path, arr: np.ndarray) -> None:
    arr = np.asarray(arr, dtype=np.uint16)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"PNG16 RGB writer expects HWC RGB, got {arr.shape}")
    h, w, _ = arr.shape
    be = arr.byteswap() if arr.dtype.byteorder in {"<", "="} else arr
    rows = [b"\x00" + be[y].tobytes() for y in range(h)]
    raw = b"".join(rows)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 16, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(raw, level=6))
        + _png_chunk(b"IEND", b"")
    )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(data)


def _paeth(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    p = a.astype(np.int16) + b.astype(np.int16) - c.astype(np.int16)
    pa = np.abs(p - a)
    pb = np.abs(p - b)
    pc = np.abs(p - c)
    return np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c)).astype(np.uint8)


def _try_read_png16_rgb(path: Path) -> np.ndarray | None:
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat = bytearray()
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        payload = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type, _, _, interlace = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break
    if (bit_depth, color_type, interlace) != (16, 2, 0) or width is None or height is None:
        return None
    row_bytes = width * 3 * 2
    raw = zlib.decompress(bytes(idat))
    out = np.zeros((height, row_bytes), dtype=np.uint8)
    prev = np.zeros(row_bytes, dtype=np.uint8)
    bpp = 6
    offset = 0
    for y in range(height):
        f = raw[offset]
        offset += 1
        row = np.frombuffer(raw[offset : offset + row_bytes], dtype=np.uint8).copy()
        offset += row_bytes
        left = np.zeros_like(row)
        left[bpp:] = row[:-bpp] if f == 1 else out[y, :-bpp]
        if f == 0:
            recon = row
        elif f == 1:
            recon = (row + left) & 0xFF
        elif f == 2:
            recon = (row + prev) & 0xFF
        elif f == 3:
            avg = ((left.astype(np.uint16) + prev.astype(np.uint16)) // 2).astype(np.uint8)
            recon = (row + avg) & 0xFF
        elif f == 4:
            upper_left = np.zeros_like(row)
            upper_left[bpp:] = prev[:-bpp]
            recon = (row + _paeth(left, prev, upper_left)) & 0xFF
        else:
            raise ValueError(f"Unsupported PNG filter {f}")
        out[y] = recon
        prev = recon
    arr = out.reshape(height, width, 3, 2)
    u16 = (arr[:, :, :, 0].astype(np.uint16) << 8) | arr[:, :, :, 1].astype(np.uint16)
    return (u16.astype(np.float32) / 65535.0).astype(np.float32)


def write_png8_preview(path: str | Path, rgb_float01: np.ndarray) -> None:
    arr = np.rint(np.clip(rgb_float01[:, :, :3], 0.0, 1.0) * 255.0).astype(np.uint8)
    Image.fromarray(arr, mode="RGB").save(path)


def detect_normal_range(arr: np.ndarray) -> str:
    rgb = np.asarray(arr)[..., :3]
    mn = float(np.nanmin(rgb))
    mx = float(np.nanmax(rgb))
    if mn < -0.1 or mx > 1.1:
        return "minus1_to1"
    if mn >= -1e-4 and mx <= 1.1:
        return "zero_to1"
    return "unknown"


def decode_packed_normal(rgb01: np.ndarray) -> np.ndarray:
    return np.asarray(rgb01, dtype=np.float32)[..., :3] * 2.0 - 1.0


def encode_packed_normal(n: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(n, dtype=np.float32)[..., :3] * 0.5 + 0.5, 0.0, 1.0)


def normalize_normal(n: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    n = np.asarray(n, dtype=np.float32)[..., :3]
    length = np.linalg.norm(n, axis=-1, keepdims=True)
    return np.where(length > eps, n / np.maximum(length, eps), n).astype(np.float32)


def apply_matrix(n: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    mat = np.asarray(matrix, dtype=np.float32).reshape(3, 3)
    return np.einsum("...c,dc->...d", np.asarray(n, dtype=np.float32)[..., :3], mat).astype(np.float32)


def angular_error(n1: np.ndarray, n2: np.ndarray) -> np.ndarray:
    a = normalize_normal(n1)
    b = normalize_normal(n2)
    dot = np.sum(a * b, axis=-1)
    return np.degrees(np.arccos(np.clip(dot, -1.0, 1.0))).astype(np.float32)


def stats_normal(n: np.ndarray) -> dict[str, Any]:
    arr = np.asarray(n, dtype=np.float32)
    rgb = arr[..., :3]
    flat = rgb.reshape(-1, 3)
    norm = np.linalg.norm(flat, axis=1)
    finite = np.isfinite(flat).all(axis=1)
    valid = flat[finite] if finite.any() else flat
    norm_valid = norm[finite] if finite.any() else norm
    return {
        "shape": list(arr.shape),
        "dtype": str(arr.dtype),
        "channels": int(arr.shape[2]) if arr.ndim == 3 else 1,
        "min": float(np.nanmin(rgb)),
        "max": float(np.nanmax(rgb)),
        "mean": [float(x) for x in np.nanmean(valid, axis=0)],
        "std": [float(x) for x in np.nanstd(valid, axis=0)],
        "p01": [float(x) for x in np.nanpercentile(valid, 1, axis=0)],
        "p50": [float(x) for x in np.nanpercentile(valid, 50, axis=0)],
        "p99": [float(x) for x in np.nanpercentile(valid, 99, axis=0)],
        "norm_mean": float(np.nanmean(norm_valid)),
        "norm_std": float(np.nanstd(norm_valid)),
        "norm_p01": float(np.nanpercentile(norm_valid, 1)),
        "norm_p99": float(np.nanpercentile(norm_valid, 99)),
    }


def heatmap(values: np.ndarray, vmax: float | None = None) -> np.ndarray:
    v = np.asarray(values, dtype=np.float32)
    if vmax is None:
        vmax = float(np.nanpercentile(v, 95)) or 1.0
    t = np.clip(v / max(vmax, 1e-6), 0.0, 1.0)
    return np.stack([t, 1.0 - np.abs(t - 0.5) * 2.0, 1.0 - t], axis=-1).astype(np.float32)


def make_montage(images: list[np.ndarray], labels: list[str], output_path: str | Path, tile_width: int = 320) -> None:
    tiles: list[Image.Image] = []
    font = ImageFont.load_default()
    label_h = 22
    for image, label in zip(images, labels):
        rgb = np.clip(image[..., :3], 0.0, 1.0)
        pil = Image.fromarray(np.rint(rgb * 255).astype(np.uint8), mode="RGB")
        scale = tile_width / max(1, pil.width)
        pil = pil.resize((tile_width, max(1, int(pil.height * scale))), Image.Resampling.BILINEAR)
        tile = Image.new("RGB", (pil.width, pil.height + label_h), (20, 20, 20))
        tile.paste(pil, (0, label_h))
        draw = ImageDraw.Draw(tile)
        draw.text((6, 4), label, fill=(240, 240, 240), font=font)
        tiles.append(tile)
    h = max(tile.height for tile in tiles)
    out = Image.new("RGB", (sum(tile.width for tile in tiles), h), (20, 20, 20))
    x = 0
    for tile in tiles:
        out.paste(tile, (x, 0))
        x += tile.width
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.save(output_path)


def write_json(path: str | Path, data: Any) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def quantization_error_estimate(n: np.ndarray) -> dict[str, float]:
    packed = encode_packed_normal(n)
    q = np.rint(packed * 65535.0) / 65535.0
    decoded = normalize_normal(decode_packed_normal(q))
    ae = angular_error(n, decoded)
    return {
        "angular_mean_deg": float(np.nanmean(ae)),
        "angular_p95_deg": float(np.nanpercentile(ae, 95)),
        "l2_mean": float(np.nanmean(np.linalg.norm(normalize_normal(n) - decoded, axis=-1))),
    }
