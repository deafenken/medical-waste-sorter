"""Convert the .pt YOLO model into NCNN format for fast Pi/RK3588 CPU inference.

Run once after cloning the repo:

    python tools/export_ncnn.py models/best.pt
    # produces models/best_ncnn_model/

Then point detector.model_path at the produced directory in config.yaml.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pt_path", type=Path,
                        help="path to the .pt model, e.g. models/best.pt")
    parser.add_argument("--format", default="ncnn",
                        choices=["ncnn", "onnx", "openvino", "torchscript"])
    args = parser.parse_args()

    if not args.pt_path.exists():
        print(f"missing model: {args.pt_path}", file=sys.stderr)
        sys.exit(1)

    from ultralytics import YOLO

    model = YOLO(str(args.pt_path))
    out = model.export(format=args.format)
    print(f"exported -> {out}")


if __name__ == "__main__":
    main()
