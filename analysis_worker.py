import argparse
import contextlib
import json
import os
import sys

import analyze_plates as analyzer


def parse_args():
    parser = argparse.ArgumentParser(description="Run one agar plate analysis and return JSON.")
    parser.add_argument("image_path")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--output-filename", default=None)
    parser.add_argument("--plate-diameter-cm", type=float, default=analyzer.KNOWN_PLATE_DIAMETER_CM)
    parser.add_argument("--growth-threshold", type=int, default=analyzer.GROWTH_DETECTION_THRESHOLD)
    parser.add_argument("--median-blur-size", type=int, default=analyzer.MEDIAN_BLUR_SIZE)
    parser.add_argument("--max-center-deviation-percent", type=float, default=analyzer.MAX_CENTER_DEVIATION_PERCENT)
    parser.add_argument("--morph-close-kernel-size", type=int, default=analyzer.MORPH_CLOSE_KERNEL_SIZE)
    parser.add_argument("--clahe-clip-limit", type=float, default=analyzer.CLAHE_CLIP_LIMIT)
    return parser.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    with contextlib.redirect_stdout(sys.stderr):
        result = analyzer.analyze_agar_plate(
            args.image_path,
            args.output_dir,
            plate_diameter_cm=args.plate_diameter_cm,
            growth_threshold=args.growth_threshold,
            median_blur_size=args.median_blur_size,
            max_center_deviation_percent=args.max_center_deviation_percent,
            morph_close_kernel_size=args.morph_close_kernel_size,
            clahe_clip_limit=args.clahe_clip_limit,
            output_filename=args.output_filename,
        )

    payload = {
        "ok": bool(result),
        "result": result,
        "error": "" if result else "Analysis failed. Check plate detection or threshold settings.",
    }
    print(json.dumps(payload))


if __name__ == "__main__":
    main()
