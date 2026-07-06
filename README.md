# EXR2PNG Normal Conversion Toolkit

This project converts normal maps between captured EXR float normals and model-style PNG/JPG packed normals. It only touches normal conversion, calibration, statistics, and visualization.

## What Is Tracked By Git

Tracked core project files:

- `tools/normal/normal_convert.py`: CLI entry point.
- `tools/normal/normal_io.py`: image I/O, normal math, stats, montage helpers.
- `configs/normal_conversion/exr_to_model_normal.yaml`: default coordinate conversion config.
- `docs/normal_exr_png_conversion.md`: longer technical notes.
- `README.md`: quick start and command reference.

Ignored local files:

- `normal/`: input dataset. Usually large and machine-local.
- `normal_converted/`: converted PNG16/EXR outputs.
- `normal_debug/`: audit, calibration, comparison reports and montage images.
- `__pycache__/`: Python bytecode cache.

## Generated Folders

`normal/`

Input folder. In this workspace it contains matching pairs such as `0003.exr` and `0003.jpg`. The EXR is treated as captured float normal data. The JPG is treated only as a model-output reference, never as a lossless conversion target.

`normal_debug/audit/`

Created by `audit`. Contains:

- `summary.csv` and `summary.json`: per-file shape, dtype, min/max, percentiles, normal length stats, guessed range, warnings.
- `audit_montage.png`: quick visual sheet for checking whether files look sane.

`normal_debug/calibration/`

Created by `calibrate`. Contains:

- `calibration_topk.csv` and `calibration_topk.json`: best signed axis permutation matrices.
- `calibration_per_pair_best.csv` and `calibration_per_pair_best.json`: best signed permutation per image. If each image wants a different matrix, the data is probably not describable by one global RGB matrix.
- `best_exr_to_model_normal.yaml`: config using the best candidate matrix.
- `montage/*.png`: visual checks for model output vs transformed EXR.
- `README_calibration.txt`: reminder that calibration is only a hint.

`normal_converted/png16_model_convention/`

Created by `exr2png`. Contains:

- `*.png`: PNG16 packed normals in model convention.
- `*_preview.png`: PNG8 preview images for human viewing.
- `*.json`: sidecar metadata and stats.
- `*.npz`: optional exact round-trip float data when `--save_npz` is used.
- `exr2png_summary.csv` and `exr2png_summary.json`: conversion summary.

`normal_converted/roundtrip_exr/`

Created by `png2exr`. Contains:

- `*.exr`: reconstructed source-convention EXR normals.
- `*_preview.png`: PNG8 previews.
- `*.json`: restore metadata and stats.
- `png2exr_summary.csv` and `png2exr_summary.json`: restore summary.

`normal_debug/compare/`

Created by `compare`. Contains:

- `compare_summary.csv` and `compare_summary.json`: numeric errors.
- `montage/*.png`: side-by-side images for visual comparison.

Each compare montage is laid out as:

1. `model output`: original model JPG/PNG from `normal/`.
2. `source packed`: source EXR packed directly for viewing, before transform.
3. `source transformed`: source EXR after YAML matrix, packed as model normal.
4. `roundtrip`: PNG16 converted back to EXR and previewed.
5. `angular error`: error heatmap for source EXR vs round-trip EXR.

To compare converted images with generated/model images, open:

```text
normal_debug/compare/montage/0003.png
```

Then compare panel 1 (`model output`) with panel 3 (`source transformed`). If those colors differ strongly, the model output and captured EXR are probably using different normal conventions, spaces, poses, or channel/sign mappings. Check `normal_debug/calibration/calibration_topk.csv` and inspect `normal_debug/calibration/montage/*.png`.

For numeric comparison, open:

```text
normal_debug/compare/compare_summary.csv
```

Important columns:

- `converted_vs_model_angular_mean_deg`: lower means converted EXR normal is closer to model JPG/PNG.
- `converted_vs_model_angular_p95_deg`: high-percentile mismatch.
- `roundtrip_angular_mean_deg`: should be tiny when using NPZ exact restore.
- `roundtrip_l2_mean`: vector error for source EXR vs reconstructed EXR.

## Requirements

Required:

```bash
pip install numpy pillow OpenEXR
```

Optional:

```bash
pip install PyYAML opencv-python imageio
```

The code has a small fallback YAML parser for the provided config, so `PyYAML` is convenient but not mandatory.

## Quick Start

Run from the project root:

```bash
python tools/normal/normal_convert.py audit \
  --normal_dir ./normal \
  --output_dir ./normal_debug/audit \
  --config configs/normal_conversion/exr_to_model_normal.yaml
```

```bash
python tools/normal/normal_convert.py calibrate \
  --source_exr_dir ./normal \
  --model_png_dir ./normal \
  --output_dir ./normal_debug/calibration \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --topk 10
```

Inspect:

```text
normal_debug/calibration/montage/
normal_debug/calibration/calibration_topk.csv
normal_debug/calibration/best_exr_to_model_normal.yaml
```

If the best matrix is visually correct, copy its `transform.matrix` into:

```text
configs/normal_conversion/exr_to_model_normal.yaml
```

For this dataset, the current calibrated default matrix is:

```yaml
transform:
  matrix:
    - [0.0, -1.0, 0.0]
    - [0.0, 0.0, 1.0]
    - [1.0, 0.0, 0.0]
```

Then convert:

```bash
python tools/normal/normal_convert.py exr2png \
  --input_dir ./normal \
  --output_dir ./normal_converted/png16_model_convention \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --save_npz \
  --save_preview
```

Round-trip back to EXR:

```bash
python tools/normal/normal_convert.py png2exr \
  --input_dir ./normal_converted/png16_model_convention \
  --output_dir ./normal_converted/roundtrip_exr \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --prefer_npz_if_available \
  --save_preview
```

Compare everything:

```bash
python tools/normal/normal_convert.py compare \
  --source_exr_dir ./normal \
  --converted_png_dir ./normal_converted/png16_model_convention \
  --roundtrip_exr_dir ./normal_converted/roundtrip_exr \
  --model_png_dir ./normal \
  --output_dir ./normal_debug/compare \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive
```

## Command Reference

### `audit`

Checks EXR/PNG/JPG files and writes statistics plus a montage.

```bash
python tools/normal/normal_convert.py audit \
  --normal_dir ./normal \
  --output_dir ./normal_debug/audit \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive
```

Parameters:

- `--normal_dir`: folder containing EXR/PNG/JPG normal files.
- `--output_dir`: where audit reports are written.
- `--config`: YAML config path.
- `--recursive`: scan subfolders too.

### `calibrate`

Searches 48 signed permutation matrices: 6 channel permutations x 8 sign flips.

```bash
python tools/normal/normal_convert.py calibrate \
  --source_exr_dir ./normal \
  --model_png_dir ./normal \
  --output_dir ./normal_debug/calibration \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --topk 10 \
  --max_side 512
```

Parameters:

- `--source_exr_dir`: folder with source EXR normals.
- `--model_png_dir`: folder with model output PNG/JPG normals.
- `--output_dir`: where calibration reports are written.
- `--config`: YAML config path.
- `--recursive`: scan subfolders too.
- `--topk`: number of best matrices to report.
- `--max_side`: downsample long side for calibration loss. Use `0` for full resolution.

### `exr2png`

Converts captured EXR normals to PNG16 packed normals in model convention.

```bash
python tools/normal/normal_convert.py exr2png \
  --input_dir ./normal \
  --output_dir ./normal_converted/png16_model_convention \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --save_npz \
  --save_preview
```

Parameters:

- `--input_dir`: folder containing source EXR files.
- `--output_dir`: destination for PNG16 outputs.
- `--config`: YAML config path.
- `--recursive`: scan subfolders too.
- `--save_npz`: write exact float sidecars for exact round-trip.
- `--save_preview`: write PNG8 preview images.

### `png2exr`

Converts model PNG/JPG or generated PNG16 normals back to source EXR convention.

```bash
python tools/normal/normal_convert.py png2exr \
  --input_dir ./normal_converted/png16_model_convention \
  --output_dir ./normal_converted/roundtrip_exr \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --prefer_npz_if_available \
  --save_preview
```

Parameters:

- `--input_dir`: folder containing PNG/JPG normal files.
- `--output_dir`: destination for reconstructed EXR files.
- `--config`: YAML config path.
- `--recursive`: scan subfolders too.
- `--prefer_npz_if_available`: if a same-stem `.npz` exists, restore original float normals exactly.
- `--save_preview`: write PNG8 preview images.

### `compare`

Compares original EXR, converted PNG, round-trip EXR, and model output PNG/JPG by matching filename stems.

```bash
python tools/normal/normal_convert.py compare \
  --source_exr_dir ./normal \
  --converted_png_dir ./normal_converted/png16_model_convention \
  --roundtrip_exr_dir ./normal_converted/roundtrip_exr \
  --model_png_dir ./normal \
  --output_dir ./normal_debug/compare \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive
```

Parameters:

- `--source_exr_dir`: original captured EXR folder.
- `--converted_png_dir`: PNG16 outputs from `exr2png`.
- `--roundtrip_exr_dir`: EXR outputs from `png2exr`.
- `--model_png_dir`: model-generated JPG/PNG reference folder.
- `--output_dir`: where compare reports and montages are written.
- `--config`: YAML config path.
- `--recursive`: scan subfolders too.
- `--pairs_csv`: optional explicit pairing CSV. Use columns `source`/`model` or `source_stem`/`model_stem`.

## Notes

PNG16 is high precision but not mathematically lossless for EXR float32 data. Use `--save_npz` and `--prefer_npz_if_available` when exact float round-trip matters.

Never use JPG as a conversion intermediate. JPG is only a reference format for model output.

All coordinate conversion comes from `transform.matrix` in the YAML config. Do not hard-code coordinate conventions in the script.

Normal map color differences are not always solvable by RGB channel permutation. Common normal representations include object/world/camera/view/tangent space. A single global matrix can fix channel order and sign convention, but it cannot convert world-space normals to camera-space normals across changing views unless camera extrinsics are available. In that case, use a per-frame view rotation, usually the normal transform derived from the camera/world matrix, then normalize before packing.
