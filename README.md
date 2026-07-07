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
- `calibration_per_pair_orthogonal.csv`: per-image fitted rotation matrices. This is the closest option to a camera/view rotation when camera pose is unavailable.
- `calibration_per_pair_linear.csv`: per-image fitted linear matrices. This usually gives the best visual alignment, but it is an approximation and is not a physically pure normal-space rotation.
- `calibration_warnings.json`: warnings when the best signed permutation is still poor.
- `best_exr_to_model_normal.yaml`: config using the best candidate matrix.
- `montage/*.png`: visual checks for model output vs transformed EXR.
- `candidate_montage/*.png`: top-k candidate visual checks. Each montage shows model output, source raw packed, candidate transformed normal, RGB difference, and fixed-range angular error.
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
4. `model rgb diff`: absolute RGB difference between model output and source transformed.
5. `angular_error_model_alignment`: fixed 0-90 degree heatmap for model output vs source transformed.
6. `roundtrip`: PNG16 converted back to EXR and previewed.
7. `angular_error_roundtrip`: fixed 0-90 degree heatmap for source EXR vs round-trip EXR.

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

- `model_align_angular_mean_deg`: lower means transformed EXR normal is closer to model JPG/PNG.
- `model_align_angular_p95_deg`: high-percentile model alignment mismatch.
- `model_align_l1_rgb` and `model_align_l2_rgb`: packed RGB-space difference for visual-style checking.
- `model_mean_normal` and `source_transformed_mean_normal`: mean decoded normal vectors for sanity checks.
- `mean_normal_angular_deg`: angle between the two mean decoded normal vectors.
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

If one global matrix is not enough, use the per-image matrices from calibration. This is the current recommended workflow for the included sample set:

```bash
python tools/normal/normal_convert.py exr2png \
  --input_dir ./normal \
  --output_dir ./normal_converted/png16_per_image_aligned \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --save_npz \
  --save_preview \
  --matrix_csv normal_debug/calibration/calibration_per_pair_best.csv
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

For per-image aligned outputs:

```bash
python tools/normal/normal_convert.py png2exr \
  --input_dir ./normal_converted/png16_per_image_aligned \
  --output_dir ./normal_converted/roundtrip_exr_per_image \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --prefer_npz_if_available \
  --save_preview \
  --matrix_csv normal_debug/calibration/calibration_per_pair_best.csv
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

For per-image aligned outputs:

```bash
python tools/normal/normal_convert.py compare \
  --source_exr_dir ./normal \
  --converted_png_dir ./normal_converted/png16_per_image_aligned \
  --roundtrip_exr_dir ./normal_converted/roundtrip_exr_per_image \
  --model_png_dir ./normal \
  --output_dir ./normal_debug/compare_per_image \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --matrix_csv normal_debug/calibration/calibration_per_pair_best.csv
```

With the current sample set, per-image alignment is much better than the single global matrix. Signed permutation per-image alignment reaches about `33.36` degrees mean model-alignment error. Per-image linear alignment reaches about `15.16` degrees mean error, with round-trip error still around `1e-6` degrees when NPZ exact restore is used. Linear alignment is the best current visual match, but it is not proof that the normals are physically in the same space.

For the strongest current visual alignment, use the linear matrix CSV:

```bash
python tools/normal/normal_convert.py exr2png \
  --input_dir ./normal \
  --output_dir ./normal_converted/png16_per_image_linear_aligned \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --save_npz \
  --save_preview \
  --matrix_csv normal_debug/calibration/calibration_per_pair_linear.csv
```

```bash
python tools/normal/normal_convert.py png2exr \
  --input_dir ./normal_converted/png16_per_image_linear_aligned \
  --output_dir ./normal_converted/roundtrip_exr_per_image_linear \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --prefer_npz_if_available \
  --save_preview \
  --matrix_csv normal_debug/calibration/calibration_per_pair_linear.csv
```

```bash
python tools/normal/normal_convert.py compare \
  --source_exr_dir ./normal \
  --converted_png_dir ./normal_converted/png16_per_image_linear_aligned \
  --roundtrip_exr_dir ./normal_converted/roundtrip_exr_per_image_linear \
  --model_png_dir ./normal \
  --output_dir ./normal_debug/compare_per_image_linear \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --matrix_csv normal_debug/calibration/calibration_per_pair_linear.csv
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
  --max_side 512 \
  --warn_degrees 30 \
  --linear_ridge 1e-4
```

Parameters:

- `--source_exr_dir`: folder with source EXR normals.
- `--model_png_dir`: folder with model output PNG/JPG normals.
- `--output_dir`: where calibration reports are written.
- `--config`: YAML config path.
- `--recursive`: scan subfolders too.
- `--topk`: number of best matrices to report.
- `--max_side`: downsample long side for calibration loss. Use `0` for full resolution.
- `--warn_degrees`: emit warning if the best signed permutation is still above this mean angular error.
- `--linear_ridge`: regularization for per-image linear matrix fitting.

### `exr2png`

Converts captured EXR normals to PNG16 packed normals in model convention.

```bash
python tools/normal/normal_convert.py exr2png \
  --input_dir ./normal \
  --output_dir ./normal_converted/png16_model_convention \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --save_npz \
  --save_preview \
  --matrix_csv normal_debug/calibration/calibration_per_pair_best.csv
```

Parameters:

- `--input_dir`: folder containing source EXR files.
- `--output_dir`: destination for PNG16 outputs.
- `--config`: YAML config path.
- `--recursive`: scan subfolders too.
- `--save_npz`: write exact float sidecars for exact round-trip.
- `--save_preview`: write PNG8 preview images.
- `--matrix_csv`: optional per-stem matrix CSV. Use `normal_debug/calibration/calibration_per_pair_best.csv` for per-image aligned conversion.

### `pose2png`

Converts world-space EXR normals to camera/view-space packed PNG normals using UE camera poses.

The expected pose format is `poses.txt`:

```text
Timestamp X Y Z Qx Qy Qz Qw
```

with UE axes:

```text
+X forward, +Y right, +Z up
```

For the updated dataset with `Normal_Cam00_Pose###.exr` and `poses.txt`, the best checked convention against `0003.jpg` is currently `right_up_backward`:

```bash
python tools/normal/normal_convert.py pose2png \
  --input_dir ./normal \
  --output_dir ./normal_converted/pose_camera_right_up_backward \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --poses ./normal/poses.txt \
  --recursive \
  --save_preview \
  --save_npz \
  --convention right_up_backward
```

For a quick single-pose check:

```bash
python tools/normal/normal_convert.py pose2png \
  --input_dir ./normal \
  --output_dir ./normal_converted/pose003_right_up_backward \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --poses ./normal/poses.txt \
  --recursive \
  --save_preview \
  --save_npz \
  --convention right_up_backward \
  --start_pose 3 \
  --end_pose 3 \
  --montage_count 1
```

Parameters:

- `--input_dir`: folder containing source EXR files.
- `--output_dir`: destination for pose-transformed PNG outputs.
- `--config`: YAML config path.
- `--poses`: UE `poses.txt` path.
- `--recursive`: scan subfolders too.
- `--save_preview`: write PNG8 preview images.
- `--save_npz`: write exact float sidecars.
- `--preview_only`: write PNG8 previews directly, useful for fast visual scans.
- `--convention`: camera normal packing convention. Repeat to output multiple variants. Current recommended value is `right_up_backward`.
- `--start_pose` and `--end_pose`: process only a pose index range.
- `--limit`: maximum number of EXR files to process.
- `--montage_count`: number of variant montages to write.

### `png2exr`

Converts model PNG/JPG or generated PNG16 normals back to source EXR convention.

```bash
python tools/normal/normal_convert.py png2exr \
  --input_dir ./normal_converted/png16_model_convention \
  --output_dir ./normal_converted/roundtrip_exr \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --prefer_npz_if_available \
  --save_preview \
  --matrix_csv normal_debug/calibration/calibration_per_pair_best.csv
```

Parameters:

- `--input_dir`: folder containing PNG/JPG normal files.
- `--output_dir`: destination for reconstructed EXR files.
- `--config`: YAML config path.
- `--recursive`: scan subfolders too.
- `--prefer_npz_if_available`: if a same-stem `.npz` exists, restore original float normals exactly.
- `--save_preview`: write PNG8 preview images.
- `--matrix_csv`: optional per-stem matrix CSV used for inverse conversion when NPZ exact restore is unavailable.

### `compare`

Compares original EXR, converted PNG, round-trip EXR, and model output PNG/JPG by matching filename stems.

`compare` reports two separate concepts:

- Round-trip error: source EXR vs reconstructed EXR. This only checks whether conversion preserved information.
- Model alignment error: model output decoded normal vs source EXR transformed by the YAML matrix. This checks whether the coordinate convention is actually aligned.

```bash
python tools/normal/normal_convert.py compare \
  --source_exr_dir ./normal \
  --converted_png_dir ./normal_converted/png16_model_convention \
  --roundtrip_exr_dir ./normal_converted/roundtrip_exr \
  --model_png_dir ./normal \
  --output_dir ./normal_debug/compare \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --matrix_csv normal_debug/calibration/calibration_per_pair_best.csv
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
- `--matrix_csv`: optional per-stem matrix CSV used for model-alignment evaluation.

## Notes

PNG16 is high precision but not mathematically lossless for EXR float32 data. Use `--save_npz` and `--prefer_npz_if_available` when exact float round-trip matters.

Never use JPG as a conversion intermediate. JPG is only a reference format for model output.

All global coordinate conversion comes from `transform.matrix` in the YAML config. Per-image matrix CSV files can override it by stem when passed with `--matrix_csv`.

Normal map color differences are not always solvable by RGB channel permutation. Common normal representations include object/world/camera/view/tangent space. A single global matrix can fix channel order and sign convention, but it cannot convert world-space normals to camera-space normals across changing views unless camera extrinsics are available. In that case, use a per-frame view rotation, usually the normal transform derived from the camera/world matrix, then normalize before packing.

The per-image linear matrix path is useful when you need a practical visual match to model output and do not have camera pose. Treat it as a calibration approximation. If you need physically meaningful normals, prefer real camera pose based world-to-view normal conversion over fitted linear matrices.
