# Normal EXR/PNG Conversion

This toolchain only handles files under a `normal/` style folder. It does not modify training code, model structure, MSV, TexEnhancer, or DiffusionRenderer logic.

## Data Model

EXR files are raw float normal maps, not color images. The first three channels are treated as the normal vector. Alpha is ignored on read by default because captured normal EXRs may have alpha filled with zero and it is not a reliable mask.

PNG16 outputs are packed normal maps:

```text
rgb = normal * 0.5 + 0.5
normal = rgb * 2.0 - 1.0
```

EXR `float32` to PNG16 is not mathematically lossless. PNG16 keeps the quantization error very small, but exact float round-trip requires `--save_npz` during `exr2png` and `--prefer_npz_if_available` during `png2exr`.

JPG is allowed only as a model-output reference. Do not use JPG as an intermediate conversion format because JPEG artifacts damage normal vectors.

Coordinate conversion is controlled by `configs/normal_conversion/exr_to_model_normal.yaml`. The `transform.matrix` maps source EXR normals to the model normal convention. The inverse matrix is used when converting PNG/JPG back to EXR.

Calibration searches only signed permutation matrices: axis reorderings and sign flips. It does not solve arbitrary rotations, camera poses, projection differences, or world-space to camera-space transforms.

## Recommended Workflow

Audit the folder:

```bash
python tools/normal/normal_convert.py audit \
  --normal_dir ./normal \
  --output_dir ./normal_debug/audit \
  --config configs/normal_conversion/exr_to_model_normal.yaml
```

Run a rough convention calibration:

```bash
python tools/normal/normal_convert.py calibrate \
  --source_exr_dir ./normal \
  --model_png_dir ./normal \
  --output_dir ./normal_debug/calibration \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --topk 10
```

Inspect `normal_debug/calibration/montage` manually. If the best matrix is reasonable, copy or merge `normal_debug/calibration/best_exr_to_model_normal.yaml` into:

```text
configs/normal_conversion/exr_to_model_normal.yaml
```

Convert EXR to PNG16 in the model convention:

```bash
python tools/normal/normal_convert.py exr2png \
  --input_dir ./normal \
  --output_dir ./normal_converted/png16_model_convention \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --save_npz \
  --save_preview
```

Convert PNG16 back to EXR:

```bash
python tools/normal/normal_convert.py png2exr \
  --input_dir ./normal_converted/png16_model_convention \
  --output_dir ./normal_converted/roundtrip_exr \
  --config configs/normal_conversion/exr_to_model_normal.yaml \
  --recursive \
  --prefer_npz_if_available \
  --save_preview
```

Compare source EXR, converted PNG, round-trip EXR, and model output JPG/PNG:

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

## Outputs

`audit` writes `summary.csv`, `summary.json`, and a preview montage. Each file reports shape, dtype, channels, min/max, mean/std, percentiles, vector norm statistics, guessed range, and possible issues.

`exr2png` writes PNG16 files, preview PNG8 files, JSON sidecars, optional compressed NPZ sidecars, and summary files. The JSON records range detection, transform matrix, inverse matrix, stats before/after transform, alpha handling, and estimated PNG16 quantization error.

`png2exr` writes float32 EXR files with RGB normal channels and alpha set to 1.0. If an NPZ sidecar is used, `restore_mode` is recorded as `exact_npz`.

`compare` writes `compare_summary.csv`, `compare_summary.json`, and per-stem montages. Metrics include angular mean/median/p95, L1, L2, norm error, and channel mean/std.

`calibrate` writes the top-k signed permutation matrices, `best_exr_to_model_normal.yaml`, and montages. Treat this as a calibration hint, not proof.

## Troubleshooting

If converted PNG and model JPG colors still differ, likely causes include:

- Model output is inaccurate.
- Source EXR and model output do not correspond to the same view.
- EXR normals are world-space while the model expects camera-space.
- Camera coordinate conventions differ.
- RGB/BGR channel order is wrong.
- A signed permutation is insufficient and camera pose is needed for a view/world transform.

EXR support depends on optional backends. Install one of these if EXR read/write fails:

```bash
pip install OpenEXR
```

or:

```bash
pip install opencv-python
```
