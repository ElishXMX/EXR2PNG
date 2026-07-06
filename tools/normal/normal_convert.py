from __future__ import annotations

import argparse
import csv
import itertools
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parent))

try:
    from normal_io import (  # type: ignore # noqa: E402
        EXR_EXTS,
        IMAGE_EXTS,
        angular_error,
        apply_matrix,
        decode_packed_normal,
        detect_normal_range,
        encode_packed_normal,
        heatmap,
        make_montage,
        normalize_normal,
        quantization_error_estimate,
        read_exr,
        read_png_or_jpg,
        stats_normal,
        write_exr,
        write_json,
        write_png16,
        write_png8_preview,
    )
except ModuleNotFoundError:
    from .normal_io import (  # type: ignore # noqa: E402
        EXR_EXTS,
        IMAGE_EXTS,
        angular_error,
        apply_matrix,
        decode_packed_normal,
        detect_normal_range,
        encode_packed_normal,
        heatmap,
        make_montage,
        normalize_normal,
        quantization_error_estimate,
        read_exr,
        read_png_or_jpg,
        stats_normal,
        write_exr,
        write_json,
        write_png16,
        write_png8_preview,
    )


def load_config(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text)
    except Exception:
        return _load_simple_yaml(text)


def _parse_scalar(value: str) -> Any:
    value = value.split("#", 1)[0].strip()
    if value in {"true", "false"}:
        return value == "true"
    if value in {"True", "False"}:
        return value == "True"
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip().strip("\"'")) for part in inner.split(",")]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value.strip("\"'")


def _load_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if line.startswith("- "):
            raise ValueError("Top-level YAML lists are not supported by fallback parser")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            parent[key] = _parse_scalar(value)
            i += 1
            continue
        if i + 1 < len(lines) and lines[i + 1].lstrip().startswith("- "):
            items: list[Any] = []
            i += 1
            while i < len(lines):
                item_raw = lines[i]
                item_indent = len(item_raw) - len(item_raw.lstrip(" "))
                if item_indent <= indent or not item_raw.lstrip().startswith("- "):
                    break
                items.append(_parse_scalar(item_raw.strip()[2:].strip()))
                i += 1
            parent[key] = items
        else:
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            i += 1
    return root


def dump_simple_yaml(data: dict[str, Any], path: str | Path) -> None:
    def fmt(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, str):
            return v
        if isinstance(v, list) and (not v or not isinstance(v[0], list)):
            return "[" + ", ".join(fmt(x) for x in v) + "]"
        return str(v)

    lines: list[str] = []
    for key, value in data.items():
        lines.append(f"{key}:")
        for subkey, subvalue in value.items():
            if isinstance(subvalue, list) and subvalue and isinstance(subvalue[0], list):
                lines.append(f"  {subkey}:")
                for row in subvalue:
                    lines.append("    - [" + ", ".join(f"{float(x):.8g}" for x in row) + "]")
            else:
                lines.append(f"  {subkey}: {fmt(subvalue)}")
        lines.append("")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def matrix_from_config(config: dict[str, Any]) -> np.ndarray:
    return np.asarray(config["transform"]["matrix"], dtype=np.float32).reshape(3, 3)


def list_files(root: str | Path, exts: set[str], recursive: bool) -> list[Path]:
    root = Path(root)
    globber = root.rglob if recursive else root.glob
    return sorted(p for p in globber("*") if p.is_file() and p.suffix.lower() in exts)


def rel_output(input_file: Path, input_root: Path, output_root: Path, suffix: str, ext: str) -> Path:
    rel = input_file.relative_to(input_root)
    return (output_root / rel).with_name(rel.stem + suffix + ext)


def normal_from_exr(path: Path, config: dict[str, Any]) -> tuple[np.ndarray, str, np.ndarray]:
    arr = read_exr(path, config.get("source", {}).get("channel_order", "RGB"))
    rgb = arr[:, :, :3].astype(np.float32)
    guessed = detect_normal_range(rgb)
    if guessed == "zero_to1":
        n = decode_packed_normal(rgb)
    else:
        n = rgb
    if config.get("source", {}).get("normalize", True):
        n = normalize_normal(n)
    return n, guessed, arr


def normal_from_image(path: Path) -> tuple[np.ndarray, str]:
    rgb = read_png_or_jpg(path)
    n = normalize_normal(decode_packed_normal(rgb))
    return n, "zero_to1"


def row_for_stats(path: Path, arr: np.ndarray, guessed: str, issue: str = "") -> dict[str, Any]:
    st = stats_normal(arr)
    return {
        "path": str(path),
        "ext": path.suffix.lower(),
        "shape": "x".join(map(str, st["shape"])),
        "dtype": st["dtype"],
        "channels": st["channels"],
        "min": st["min"],
        "max": st["max"],
        "mean": json.dumps(st["mean"]),
        "std": json.dumps(st["std"]),
        "p01": json.dumps(st["p01"]),
        "p50": json.dumps(st["p50"]),
        "p99": json.dumps(st["p99"]),
        "norm_mean": st["norm_mean"],
        "norm_std": st["norm_std"],
        "norm_p01": st["norm_p01"],
        "norm_p99": st["norm_p99"],
        "guessed_range": guessed,
        "possible_issue": issue,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    preferred = ["path", "stem", "source", "output", "ext", "shape", "dtype", "channels", "possible_issue", "error"]
    fieldnames = [x for x in preferred if x in fieldnames] + [x for x in fieldnames if x not in preferred]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def cmd_audit(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    out = Path(args.output_dir)
    files = list_files(args.normal_dir, EXR_EXTS | IMAGE_EXTS, args.recursive)
    rows: list[dict[str, Any]] = []
    montage_images: list[np.ndarray] = []
    montage_labels: list[str] = []
    for path in files:
        try:
            if path.suffix.lower() in EXR_EXTS:
                n, guessed, _ = normal_from_exr(path, config)
                preview = encode_packed_normal(n)
                issue = "" if guessed != "unknown" else "range_unknown"
            else:
                preview = read_png_or_jpg(path)
                n = decode_packed_normal(preview)
                guessed = "zero_to1"
                issue = "jpeg_reference_not_lossless" if path.suffix.lower() in {".jpg", ".jpeg"} else ""
            rows.append(row_for_stats(path, n, guessed, issue))
            if len(montage_images) < 24:
                montage_images.append(preview)
                montage_labels.append(path.name)
        except Exception as exc:
            rows.append({"path": str(path), "ext": path.suffix.lower(), "possible_issue": str(exc)})
    write_csv(out / "summary.csv", rows)
    write_json(out / "summary.json", rows)
    if montage_images:
        make_montage(montage_images, montage_labels, out / "audit_montage.png")


def cmd_exr2png(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    matrix = matrix_from_config(config)
    inv = np.linalg.inv(matrix)
    input_root = Path(args.input_dir)
    output_root = Path(args.output_dir)
    rows: list[dict[str, Any]] = []
    for path in list_files(input_root, EXR_EXTS, args.recursive):
        n_source, guessed, raw_arr = normal_from_exr(path, config)
        n_model = normalize_normal(apply_matrix(n_source, matrix))
        packed = encode_packed_normal(n_model)
        out_png = rel_output(path, input_root, output_root, "", ".png")
        out_png.parent.mkdir(parents=True, exist_ok=True)
        write_png16(out_png, packed)
        if args.save_preview or config.get("output", {}).get("save_preview_png8", True):
            write_png8_preview(out_png.with_name(out_png.stem + "_preview.png"), packed)
        qerr = quantization_error_estimate(n_model)
        meta = {
            "source_path": str(path),
            "output_path": str(out_png),
            "source_shape": list(raw_arr.shape),
            "source_range_guess": guessed,
            "transform_matrix": matrix.tolist(),
            "inverse_matrix": inv.tolist(),
            "png_bit_depth": 16,
            "alpha": "ignored_from_source",
            "stats_source_normal": stats_normal(n_source),
            "stats_model_normal": stats_normal(n_model),
            "quantization_error_estimate": qerr,
        }
        write_json(out_png.with_suffix(".json"), meta)
        if args.save_npz or config.get("roundtrip", {}).get("save_npz_sidecar", False):
            np.savez_compressed(
                out_png.with_suffix(".npz"),
                source_normal_float32=n_source.astype(np.float32),
                transformed_normal_float32=n_model.astype(np.float32),
                matrix=matrix.astype(np.float32),
                inverse_matrix=inv.astype(np.float32),
                metadata=json.dumps(meta, ensure_ascii=False),
            )
        rows.append({"source": str(path), "output": str(out_png), "range": guessed, **qerr})
    write_csv(output_root / "exr2png_summary.csv", rows)
    write_json(output_root / "exr2png_summary.json", rows)


def cmd_png2exr(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    matrix = matrix_from_config(config)
    inv = np.linalg.inv(matrix)
    input_root = Path(args.input_dir)
    output_root = Path(args.output_dir)
    rows: list[dict[str, Any]] = []
    for path in list_files(input_root, IMAGE_EXTS, args.recursive):
        if path.name.endswith("_preview.png"):
            continue
        npz_path = path.with_suffix(".npz")
        restore_mode = "inverse_matrix"
        warning = ""
        if args.prefer_npz_if_available and npz_path.exists():
            n_source = np.load(npz_path)["source_normal_float32"].astype(np.float32)
            restore_mode = "exact_npz"
        else:
            n_model, _ = normal_from_image(path)
            n_source = normalize_normal(apply_matrix(n_model, inv))
            if path.suffix.lower() in {".jpg", ".jpeg"}:
                warning = "8-bit JPEG is not lossless normal data"
            elif path.suffix.lower() == ".png":
                try:
                    from PIL import Image

                    bits = np.asarray(Image.open(path)).dtype
                    if bits == np.uint8:
                        warning = "8-bit PNG is preview/reference, not lossless"
                except Exception:
                    pass
        out_exr = rel_output(path, input_root, output_root, "", ".exr")
        out_exr.parent.mkdir(parents=True, exist_ok=True)
        alpha = np.ones(n_source.shape[:2] + (1,), dtype=np.float32)
        write_exr(out_exr, np.concatenate([n_source, alpha], axis=2))
        packed = encode_packed_normal(n_source)
        if args.save_preview or config.get("output", {}).get("save_preview_png8", True):
            write_png8_preview(out_exr.with_name(out_exr.stem + "_preview.png"), packed)
        meta = {
            "source_path": str(path),
            "output_path": str(out_exr),
            "restore_mode": restore_mode,
            "warning": warning,
            "transform_matrix": matrix.tolist(),
            "inverse_matrix": inv.tolist(),
            "alpha_written": 1.0,
            "stats_source_normal": stats_normal(n_source),
        }
        write_json(out_exr.with_suffix(".json"), meta)
        rows.append({"source": str(path), "output": str(out_exr), "restore_mode": restore_mode, "warning": warning})
    write_csv(output_root / "png2exr_summary.csv", rows)
    write_json(output_root / "png2exr_summary.json", rows)


def stems_map(files: list[Path]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in files:
        result.setdefault(path.stem.replace("_preview", ""), path)
    return result


def load_pairs(args: argparse.Namespace) -> list[tuple[str, str]]:
    if not args.pairs_csv:
        return []
    pairs: list[tuple[str, str]] = []
    with Path(args.pairs_csv).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            pairs.append((row.get("source") or row.get("source_stem") or "", row.get("model") or row.get("model_stem") or ""))
    return pairs


def compare_normals(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    if a.shape[:2] != b.shape[:2]:
        from PIL import Image

        planes = []
        for c in range(3):
            plane = Image.fromarray(b[..., c].astype(np.float32), mode="F")
            plane = plane.resize((a.shape[1], a.shape[0]), Image.Resampling.BILINEAR)
            planes.append(np.asarray(plane, dtype=np.float32))
        b = normalize_normal(np.stack(planes, axis=-1))
    diff = a - b
    ae = angular_error(a, b)
    return {
        "angular_mean_deg": float(np.nanmean(ae)),
        "angular_median_deg": float(np.nanmedian(ae)),
        "angular_p95_deg": float(np.nanpercentile(ae, 95)),
        "l1_mean": float(np.nanmean(np.abs(diff))),
        "l2_mean": float(np.nanmean(np.linalg.norm(diff, axis=-1))),
        "norm_error_mean": float(np.nanmean(np.abs(np.linalg.norm(a, axis=-1) - np.linalg.norm(b, axis=-1)))),
        "channel_mean": json.dumps([float(x) for x in np.nanmean(diff.reshape(-1, 3), axis=0)]),
        "channel_std": json.dumps([float(x) for x in np.nanstd(diff.reshape(-1, 3), axis=0)]),
    }


def compare_model_alignment(n_exr_model: np.ndarray, n_model: np.ndarray) -> dict[str, Any]:
    n_model = resize_normal_to(n_model, n_exr_model.shape[:2])
    normal_metrics = compare_normals(n_exr_model, n_model)
    rgb_exr = encode_packed_normal(n_exr_model)
    rgb_model = encode_packed_normal(n_model)
    rgb_diff = rgb_exr - rgb_model
    model_mean = np.nanmean(n_model.reshape(-1, 3), axis=0)
    source_mean = np.nanmean(n_exr_model.reshape(-1, 3), axis=0)
    mean_angle = float(angular_error(source_mean.reshape(1, 1, 3), model_mean.reshape(1, 1, 3))[0, 0])
    return {
        "model_align_angular_mean_deg": normal_metrics["angular_mean_deg"],
        "model_align_angular_median_deg": normal_metrics["angular_median_deg"],
        "model_align_angular_p95_deg": normal_metrics["angular_p95_deg"],
        "model_align_l1_normal": normal_metrics["l1_mean"],
        "model_align_l2_normal": normal_metrics["l2_mean"],
        "model_align_l1_rgb": float(np.nanmean(np.abs(rgb_diff))),
        "model_align_l2_rgb": float(np.nanmean(np.linalg.norm(rgb_diff, axis=-1))),
        "model_align_channel_mean": normal_metrics["channel_mean"],
        "model_align_channel_std": normal_metrics["channel_std"],
        "model_mean_normal": json.dumps([float(x) for x in model_mean]),
        "source_transformed_mean_normal": json.dumps([float(x) for x in source_mean]),
        "mean_normal_angular_deg": mean_angle,
    }


def resize_normal_to(n: np.ndarray, hw: tuple[int, int]) -> np.ndarray:
    if n.shape[:2] == hw:
        return n
    from PIL import Image

    h, w = hw
    planes = []
    for c in range(3):
        plane = Image.fromarray(n[..., c].astype(np.float32), mode="F")
        plane = plane.resize((w, h), Image.Resampling.BILINEAR)
        planes.append(np.asarray(plane, dtype=np.float32))
    return normalize_normal(np.stack(planes, axis=-1))


def downsample_normal_max_side(n: np.ndarray, max_side: int) -> np.ndarray:
    if max_side <= 0:
        return n
    h, w = n.shape[:2]
    side = max(h, w)
    if side <= max_side:
        return n
    scale = max_side / side
    return resize_normal_to(n, (max(1, int(round(h * scale))), max(1, int(round(w * scale)))))


def cmd_compare(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    matrix = matrix_from_config(config)
    out = Path(args.output_dir)
    source = stems_map(list_files(args.source_exr_dir, EXR_EXTS, args.recursive))
    converted = stems_map(list_files(args.converted_png_dir, {".png"}, args.recursive))
    roundtrip = stems_map(list_files(args.roundtrip_exr_dir, EXR_EXTS, args.recursive))
    model = stems_map(list_files(args.model_png_dir, IMAGE_EXTS, args.recursive))
    rows: list[dict[str, Any]] = []
    for stem, src_path in source.items():
        try:
            n_src, _, _ = normal_from_exr(src_path, config)
            row: dict[str, Any] = {"stem": stem}
            images: list[np.ndarray] = []
            labels: list[str] = []
            if stem in model:
                n_model, _ = normal_from_image(model[stem])
                n_model_for_error = resize_normal_to(n_model, n_src.shape[:2])
                images.append(encode_packed_normal(n_model))
                labels.append("model output")
            else:
                n_model_for_error = None
            images.append(encode_packed_normal(n_src))
            labels.append("source packed")
            n_transformed = normalize_normal(apply_matrix(n_src, matrix))
            images.append(encode_packed_normal(n_transformed))
            labels.append("source transformed")
            if n_model_for_error is not None:
                row.update(compare_model_alignment(n_transformed, n_model_for_error))
                images.append(np.abs(encode_packed_normal(n_transformed) - encode_packed_normal(n_model_for_error)))
                labels.append("model rgb diff")
                images.append(heatmap(angular_error(n_transformed, n_model_for_error), vmax=90.0))
                labels.append("angular_error_model_alignment")
            if stem in roundtrip:
                n_round, _, _ = normal_from_exr(roundtrip[stem], config)
                row.update({f"roundtrip_{k}": v for k, v in compare_normals(n_src, n_round).items()})
                images.append(encode_packed_normal(n_round))
                labels.append("roundtrip")
                images.append(heatmap(angular_error(n_src, n_round), vmax=90.0))
                labels.append("angular_error_roundtrip")
            if stem in converted and stem in model:
                n_conv, _ = normal_from_image(converted[stem])
                n_model_file, _ = normal_from_image(model[stem])
                row.update({f"converted_file_vs_model_{k}": v for k, v in compare_normals(n_conv, n_model_file).items()})
            if images:
                make_montage(images, labels, out / "montage" / f"{stem}.png")
            rows.append(row)
        except Exception as exc:
            rows.append({"stem": stem, "error": str(exc)})
    write_csv(out / "compare_summary.csv", rows)
    write_json(out / "compare_summary.json", rows)


def signed_permutation_matrices() -> list[np.ndarray]:
    mats = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product([-1.0, 1.0], repeat=3):
            mat = np.zeros((3, 3), dtype=np.float32)
            for out_axis, src_axis in enumerate(perm):
                mat[out_axis, src_axis] = signs[out_axis]
            mats.append(mat)
    return mats


def dot_loss(n1: np.ndarray, n2: np.ndarray) -> float:
    a = normalize_normal(n1)
    b = normalize_normal(n2)
    return float(np.nanmean(1.0 - np.clip(np.sum(a * b, axis=-1), -1.0, 1.0)))


def matrix_is_identity(matrix: np.ndarray, atol: float = 1e-6) -> bool:
    return bool(np.allclose(matrix, np.eye(3, dtype=np.float32), atol=atol))


def cmd_calibrate(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    out = Path(args.output_dir)
    source = stems_map(list_files(args.source_exr_dir, EXR_EXTS, args.recursive))
    model = stems_map(list_files(args.model_png_dir, IMAGE_EXTS, args.recursive))
    pairs = [(stem, source[stem], model[stem]) for stem in sorted(source.keys() & model.keys())]
    if not pairs:
        raise RuntimeError("No matching EXR/model PNG/JPG pairs found by stem.")
    matrices = signed_permutation_matrices()
    dot_loss_sums = np.zeros(len(matrices), dtype=np.float64)
    angular_sums = np.zeros(len(matrices), dtype=np.float64)
    per_pair_rows: list[dict[str, Any]] = []
    per_pair_dot_losses: list[np.ndarray] = []
    per_pair_angular_losses: list[np.ndarray] = []
    for _, src_path, model_path in pairs:
        n_src, _, _ = normal_from_exr(src_path, config)
        n_src = downsample_normal_max_side(n_src, args.max_side)
        n_model, _ = normal_from_image(model_path)
        n_model = resize_normal_to(n_model, n_src.shape[:2])
        pair_dot_losses = np.zeros(len(matrices), dtype=np.float64)
        pair_angular_losses = np.zeros(len(matrices), dtype=np.float64)
        for i, mat in enumerate(matrices):
            n_pred = normalize_normal(apply_matrix(n_src, mat))
            dloss = dot_loss(n_pred, n_model)
            aloss = float(np.nanmean(angular_error(n_pred, n_model)))
            dot_loss_sums[i] += dloss
            angular_sums[i] += aloss
            pair_dot_losses[i] = dloss
            pair_angular_losses[i] = aloss
        best_i = int(np.argmin(pair_dot_losses))
        per_pair_dot_losses.append(pair_dot_losses)
        per_pair_angular_losses.append(pair_angular_losses)
        per_pair_rows.append(
            {
                "stem": src_path.stem,
                "best_dot_loss": float(pair_dot_losses[best_i]),
                "best_angular_mean_deg": float(pair_angular_losses[best_i]),
                "best_matrix": json.dumps(matrices[best_i].tolist()),
                "global_best_dot_loss": "",
                "global_best_loss_deg": "",
            }
        )
    candidates = [
        {
            "matrix": mat,
            "dot_loss": float(dot_loss_sums[i] / len(pairs)),
            "angular_mean_deg": float(angular_sums[i] / len(pairs)),
        }
        for i, mat in enumerate(matrices)
    ]
    candidates.sort(key=lambda x: x["dot_loss"])
    rows = [
        {
            "rank": i + 1,
            "dot_loss": c["dot_loss"],
            "angular_mean_deg": c["angular_mean_deg"],
            "is_identity": matrix_is_identity(c["matrix"]),
            "matrix": json.dumps(c["matrix"].tolist()),
        }
        for i, c in enumerate(candidates[: args.topk])
    ]
    write_csv(out / "calibration_topk.csv", rows)
    write_json(
        out / "calibration_topk.json",
        [
            {
                "rank": i + 1,
                "dot_loss": c["dot_loss"],
                "angular_mean_deg": c["angular_mean_deg"],
                "is_identity": matrix_is_identity(c["matrix"]),
                "matrix": c["matrix"].tolist(),
            }
            for i, c in enumerate(candidates[: args.topk])
        ],
    )
    best = np.asarray(candidates[0]["matrix"], dtype=np.float32)
    global_best_i = next(i for i, mat in enumerate(matrices) if np.array_equal(mat, best))
    for row, pair_dot_losses, pair_angular_losses in zip(per_pair_rows, per_pair_dot_losses, per_pair_angular_losses):
        row["global_best_dot_loss"] = float(pair_dot_losses[global_best_i])
        row["global_best_loss_deg"] = float(pair_angular_losses[global_best_i])
    write_csv(out / "calibration_per_pair_best.csv", per_pair_rows)
    write_json(out / "calibration_per_pair_best.json", per_pair_rows)
    best_config = json.loads(json.dumps(config))
    best_config["transform"]["matrix"] = best.tolist()
    dump_simple_yaml(best_config, out / "best_exr_to_model_normal.yaml")
    for stem, src_path, model_path in pairs[: min(24, len(pairs))]:
        n_src, _, _ = normal_from_exr(src_path, config)
        n_model, _ = normal_from_image(model_path)
        n_model_for_error = resize_normal_to(n_model, n_src.shape[:2])
        n_best = normalize_normal(apply_matrix(n_src, best))
        make_montage(
            [encode_packed_normal(n_model), encode_packed_normal(n_src), encode_packed_normal(n_best), heatmap(angular_error(n_best, n_model_for_error))],
            ["model output", "source packed", "best transformed", "angular error"],
            out / "montage" / f"{stem}.png",
        )
    montage_pairs = pairs[: min(3, len(pairs))]
    for rank, candidate in enumerate(candidates[: args.topk], start=1):
        mat = np.asarray(candidate["matrix"], dtype=np.float32)
        for stem, src_path, model_path in montage_pairs:
            n_src, _, _ = normal_from_exr(src_path, config)
            n_model, _ = normal_from_image(model_path)
            n_model_for_error = resize_normal_to(n_model, n_src.shape[:2])
            n_candidate = normalize_normal(apply_matrix(n_src, mat))
            make_montage(
                [
                    encode_packed_normal(n_model),
                    encode_packed_normal(n_src),
                    encode_packed_normal(n_candidate),
                    np.abs(encode_packed_normal(n_candidate) - encode_packed_normal(n_model_for_error)),
                    heatmap(angular_error(n_candidate, n_model_for_error), vmax=90.0),
                ],
                ["model output", "source raw packed", f"candidate rank {rank}", "rgb difference", "angular error 0-90deg"],
                out / "candidate_montage" / f"rank_{rank:02d}_{stem}.png",
            )
    warnings: list[str] = []
    if float(candidates[0]["angular_mean_deg"]) > args.warn_degrees:
        warnings.append(
            "Best signed permutation is still poor. EXR normal may be in world-space while model output is camera-space, "
            "or model output is not a reliable GT. A camera rotation based transform may be required."
        )
    if matrix_is_identity(best) and float(candidates[0]["angular_mean_deg"]) > args.warn_degrees:
        warnings.append("Identity transform preserves roundtrip but does not align to model normal convention.")
    note = (
        "Calibration searched 48 signed permutation matrices. Inspect montage manually; "
        "model output quality, pose mismatch, world/camera space differences, or RGB/BGR mistakes can dominate this score."
    )
    if warnings:
        note += "\n\nWarnings:\n" + "\n".join(f"- {w}" for w in warnings)
    (out / "README_calibration.txt").write_text(note, encoding="utf-8")
    write_json(out / "calibration_warnings.json", warnings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Normal EXR <-> PNG/JPG conversion, audit, compare, and calibration tools.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit")
    audit.add_argument("--normal_dir", required=True)
    audit.add_argument("--output_dir", required=True)
    audit.add_argument("--config", required=True)
    audit.add_argument("--recursive", action="store_true")
    audit.set_defaults(func=cmd_audit)

    exr2png = sub.add_parser("exr2png")
    exr2png.add_argument("--input_dir", required=True)
    exr2png.add_argument("--output_dir", required=True)
    exr2png.add_argument("--config", required=True)
    exr2png.add_argument("--recursive", action="store_true")
    exr2png.add_argument("--save_npz", action="store_true")
    exr2png.add_argument("--save_preview", action="store_true")
    exr2png.set_defaults(func=cmd_exr2png)

    png2exr = sub.add_parser("png2exr")
    png2exr.add_argument("--input_dir", required=True)
    png2exr.add_argument("--output_dir", required=True)
    png2exr.add_argument("--config", required=True)
    png2exr.add_argument("--recursive", action="store_true")
    png2exr.add_argument("--prefer_npz_if_available", action="store_true")
    png2exr.add_argument("--save_preview", action="store_true")
    png2exr.set_defaults(func=cmd_png2exr)

    compare = sub.add_parser("compare")
    compare.add_argument("--source_exr_dir", required=True)
    compare.add_argument("--converted_png_dir", required=True)
    compare.add_argument("--roundtrip_exr_dir", required=True)
    compare.add_argument("--model_png_dir", required=True)
    compare.add_argument("--output_dir", required=True)
    compare.add_argument("--config", required=True)
    compare.add_argument("--recursive", action="store_true")
    compare.add_argument("--pairs_csv")
    compare.set_defaults(func=cmd_compare)

    calibrate = sub.add_parser("calibrate")
    calibrate.add_argument("--source_exr_dir", required=True)
    calibrate.add_argument("--model_png_dir", required=True)
    calibrate.add_argument("--output_dir", required=True)
    calibrate.add_argument("--config", required=True)
    calibrate.add_argument("--recursive", action="store_true")
    calibrate.add_argument("--topk", type=int, default=10)
    calibrate.add_argument("--max_side", type=int, default=512, help="Downsample normal maps for calibration loss; use 0 for full resolution.")
    calibrate.add_argument("--warn_degrees", type=float, default=30.0, help="Warn when best model-alignment angular mean remains above this threshold.")
    calibrate.set_defaults(func=cmd_calibrate)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    Path(getattr(args, "output_dir", ".")).mkdir(parents=True, exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
