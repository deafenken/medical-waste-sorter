"""Export YOLOv8 model to NCNN with optional INT8 quantization.

Three usage modes:

    # 1. FP16 export — no calibration data needed, ~2x faster than FP32
    python tools/quantize_ncnn.py models/best.pt

    # 2. INT8 quantization — needs a calibration set captured with
    #    tools/capture_calib_set.py (~50-200 representative frames)
    python tools/quantize_ncnn.py models/best.pt --int8 --calib calib_set

    # 3. Skip Ultralytics export, just print NCNN command line for manual use
    python tools/quantize_ncnn.py --print-only

INT8 caveats:
  * Expect 1-3% mAP drop versus FP16
  * Verify on real scene before deployment (run model on a few held-out images)
  * If accuracy drops too much, fall back to FP16

After exporting, point your config.yaml at the new directory:

    detector:
      backend: ncnn
      model_path: models/best_ncnn_int8_model    # FP16 default name is best_ncnn_model
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pt_path", nargs="?", type=Path,
                        default=Path("models/best.pt"),
                        help="path to .pt model")
    parser.add_argument("--int8", action="store_true",
                        help="enable INT8 quantization (needs --calib)")
    parser.add_argument("--calib", type=Path, default=None,
                        help="calibration image directory (for --int8)")
    parser.add_argument("--imgsz", type=int, default=640,
                        help="export image size")
    parser.add_argument("--print-only", action="store_true",
                        help="just print manual NCNN cli commands and exit")
    args = parser.parse_args()

    if args.print_only:
        print("=" * 70)
        print("Manual NCNN INT8 quantization (if Ultralytics export breaks):")
        print("=" * 70)
        print("""
  # 1) Export to ONNX
  python tools/quantize_ncnn.py models/best.pt --print-only --skip-ncnn

  # 2) Convert ONNX -> NCNN
  onnx2ncnn models/best.onnx best.param best.bin

  # 3) Optimize
  ncnnoptimize best.param best.bin best_opt.param best_opt.bin 65536

  # 4) Generate calibration table
  ncnn2table -p best_opt.param -b best_opt.bin -i calib_set/ \\
      -o best.table -m 127.5,127.5,127.5 -n 0.0078125,0.0078125,0.0078125 \\
      -s 640,640 -c -t 8

  # 5) Quantize
  ncnn2int8 best_opt.param best_opt.bin best_int8.param best_int8.bin best.table

  # 6) Wrap in a directory layout matching Ultralytics export
  mkdir -p models/best_ncnn_int8_model
  mv best_int8.param models/best_ncnn_int8_model/model.ncnn.param
  mv best_int8.bin   models/best_ncnn_int8_model/model.ncnn.bin
  cp models/best_ncnn_model/metadata.yaml models/best_ncnn_int8_model/
""")
        return

    if not args.pt_path.exists():
        print(f"ERROR: {args.pt_path} not found", file=sys.stderr)
        sys.exit(1)

    if args.int8:
        if args.calib is None:
            print("ERROR: --int8 requires --calib <calibration image dir>",
                  file=sys.stderr)
            print("Capture one with:  python tools/capture_calib_set.py",
                  file=sys.stderr)
            sys.exit(2)
        if not args.calib.exists():
            print(f"ERROR: calibration dir not found: {args.calib}",
                  file=sys.stderr)
            sys.exit(2)
        # ultralytics expects a YAML with 'path' + 'val' keys for INT8 export
        data_yaml = args.calib / "data.yaml"
        if not data_yaml.exists():
            data_yaml.write_text(
                f"path: {args.calib.resolve()}\n"
                f"train: .\n"
                f"val: .\n"
                f"names: {{0: dummy}}\n"
            )
            print(f"wrote stub {data_yaml}")

    print(f"loading {args.pt_path} ...")
    from ultralytics import YOLO

    model = YOLO(str(args.pt_path))
    export_kwargs = dict(format="ncnn", imgsz=args.imgsz)
    if args.int8:
        export_kwargs["int8"] = True
        export_kwargs["data"] = str(args.calib / "data.yaml")
    print(f"exporting with {export_kwargs} ...")
    out = model.export(**export_kwargs)
    print(f"\nexported -> {out}")

    if args.int8:
        # Ultralytics names the int8 export same as fp16 — rename so user
        # can keep both.
        out_path = Path(out)
        if out_path.exists() and "int8" not in out_path.name:
            new_path = out_path.with_name(out_path.name.replace("_ncnn_model",
                                                                "_ncnn_int8_model"))
            if new_path.exists():
                shutil.rmtree(new_path)
            shutil.move(str(out_path), str(new_path))
            print(f"renamed -> {new_path}")
            print(f"\nUpdate config.yaml:")
            print(f"  detector:")
            print(f"    backend: ncnn")
            print(f"    model_path: {new_path.relative_to(Path.cwd())}")


if __name__ == "__main__":
    main()
