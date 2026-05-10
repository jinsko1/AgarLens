import csv
import math
import os
import sys

import cv2
import numpy as np

import count_colonies as legacy_count_colonies


PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
MODEL_PATH = os.path.join(PROJECT_DIR, "runs", "detect", "train-5", "weights", "best.pt")
IMG_SIZE = 1024
DEFAULT_IOU = 0.50
DEFAULT_MAX_DET = 1000
INNER_PLATE_FRACTION = 0.97
MIN_BOX_FRACTION_INSIDE_PLATE = 0.50
TOO_MANY_TO_COUNT_LIMIT = legacy_count_colonies.TOO_MANY_TO_COUNT_LIMIT

_model = None
_torch = None
_yolo_class = None


def get_torch():
    global _torch
    if _torch is None:
        try:
            import torch as torch_module
        except ImportError:
            _torch = False
        else:
            _torch = torch_module
    return None if _torch is False else _torch


def get_yolo_class():
    global _yolo_class
    if _yolo_class is None:
        try:
            from ultralytics import YOLO as yolo_class
        except ImportError as exc:
            raise ImportError("The ultralytics package is required for YOLO colony counting.") from exc
        _yolo_class = yolo_class
    return _yolo_class


def get_device():
    torch = get_torch()
    if torch is not None:
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return 0
    return "cpu"


def get_model():
    global _model
    if _model is None:
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f"YOLO model not found at {MODEL_PATH}. Add your trained best.pt file there."
            )
        YOLO = get_yolo_class()
        _model = YOLO(MODEL_PATH)
    return _model


def sensitivity_to_confidence(sensitivity):
    value = min(100.0, max(0.0, float(sensitivity)))
    conf = 0.35 - (value / 100.0) * 0.25
    return max(0.05, min(0.35, conf))


def clamp_box(box, width, height):
    x1, y1, x2, y2 = box
    x1 = int(max(0, min(width - 1, round(float(x1)))))
    y1 = int(max(0, min(height - 1, round(float(y1)))))
    x2 = int(max(0, min(width, round(float(x2)))))
    y2 = int(max(0, min(height, round(float(y2)))))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def box_center(box):
    x1, y1, x2, y2 = box
    return int(round((x1 + x2) / 2)), int(round((y1 + y2) / 2))


def box_center_inside_mask(box, mask):
    cx, cy = box_center(box)
    height, width = mask.shape[:2]
    if cx < 0 or cy < 0 or cx >= width or cy >= height:
        return False
    return bool(mask[cy, cx] > 0)


def box_fraction_inside_mask(box, mask):
    height, width = mask.shape[:2]
    x1, y1, x2, y2 = clamp_box(box, width, height)
    if x2 <= x1 or y2 <= y1:
        return 0.0
    box_mask = mask[y1:y2, x1:x2]
    total_pixels = float((x2 - x1) * (y2 - y1))
    return float(np.count_nonzero(box_mask) / total_pixels) if total_pixels else 0.0


def write_yolo_debug_csv(path, rows):
    fieldnames = [
        "image",
        "detection_id",
        "accepted",
        "reject_reason",
        "x1",
        "y1",
        "x2",
        "y2",
        "cx",
        "cy",
        "width",
        "height",
        "area",
        "confidence",
        "fraction_inside_plate",
    ]
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def detection_debug_row(filename, detection_id, accepted, reject_reason, box, confidence, fraction_inside_plate):
    x1, y1, x2, y2 = box
    cx, cy = box_center(box)
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    return {
        "image": filename,
        "detection_id": detection_id,
        "accepted": bool(accepted),
        "reject_reason": reject_reason,
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "cx": cx,
        "cy": cy,
        "width": width,
        "height": height,
        "area": width * height,
        "confidence": round(float(confidence), 4),
        "fraction_inside_plate": round(float(fraction_inside_plate), 4),
    }


def draw_count_text(output_image, text):
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1
    font_thickness = 2
    text_size = cv2.getTextSize(text, font, font_scale, font_thickness)[0]
    text_x = max(20, output_image.shape[1] - text_size[0] - 20)
    text_y = output_image.shape[0] - 20
    cv2.putText(output_image, text, (text_x, text_y), font, font_scale, (255, 255, 255), font_thickness)


def crop_around_plate(image, plate_x, plate_y, plate_r, margin_fraction=0.08):
    height, width = image.shape[:2]
    margin = int(max(20, plate_r * margin_fraction))
    x1 = max(0, int(plate_x - plate_r - margin))
    y1 = max(0, int(plate_y - plate_r - margin))
    x2 = min(width, int(plate_x + plate_r + margin))
    y2 = min(height, int(plate_y + plate_r + margin))
    if x2 <= x1 or y2 <= y1:
        return image, [0, 0, width, height]
    return image[y1:y2, x1:x2].copy(), [x1, y1, x2, y2]


def process_image(
    image_path,
    output_dir,
    binary_threshold=30,
    erosion_iterations=0,
    min_solidity=0.9,
    min_colony_area=15,
    max_colony_area=4000,
    sensitivity=50,
    colony_size="Medium",
    split_touching=True,
    output_filename=None,
    return_details=False,
    save_diagnostics=False,
    diagnostic_dir=None,
):
    filename = os.path.basename(image_path)
    print(f"\nProcessing {filename} with YOLO colony detector...")

    original_image = cv2.imread(image_path)
    if original_image is None:
        print(f"Error: Could not read image at {image_path}")
        if return_details:
            return None
        return filename, 0

    output_image = original_image.copy()
    height, width = original_image.shape[:2]
    gray_image = cv2.cvtColor(original_image, cv2.COLOR_BGR2GRAY)

    plate = legacy_count_colonies.detect_plate(gray_image)
    if plate is None:
        print(f"  - No agar plate detected in {filename}.")
        if return_details:
            return None
        return filename, 0

    plate_x, plate_y, plate_r = plate
    inner_radius = int(plate_r * INNER_PLATE_FRACTION)
    allowed_plate_mask = np.zeros_like(gray_image, dtype=np.uint8)
    cv2.circle(allowed_plate_mask, (plate_x, plate_y), inner_radius, 255, -1)

    masked_image = original_image.copy()
    masked_image[allowed_plate_mask == 0] = 0

    conf = sensitivity_to_confidence(sensitivity)
    try:
        model = get_model()
        predictions = model.predict(
            source=masked_image,
            imgsz=IMG_SIZE,
            conf=conf,
            iou=DEFAULT_IOU,
            max_det=DEFAULT_MAX_DET,
            device=get_device(),
            verbose=False,
        )
    except (ImportError, FileNotFoundError, RuntimeError, OSError) as exc:
        print(f"  - YOLO prediction failed: {exc}")
        if return_details:
            return None
        return filename, 0

    boxes = predictions[0].boxes if predictions and predictions[0].boxes is not None else None
    xyxy = boxes.xyxy.cpu().numpy() if boxes is not None else np.empty((0, 4))
    confidences = boxes.conf.cpu().numpy() if boxes is not None else np.empty((0,))

    final_colonies = []
    debug_rows = []
    too_many_to_count = False

    for detection_id, (box, confidence) in enumerate(zip(xyxy, confidences), start=1):
        clamped_box = clamp_box(box, width, height)
        x1, y1, x2, y2 = clamped_box
        area = max(0, x2 - x1) * max(0, y2 - y1)
        fraction_inside = box_fraction_inside_mask(clamped_box, allowed_plate_mask)
        accepted = True
        reject_reason = ""

        if area < 1:
            accepted = False
            reject_reason = "invalid_box"
        elif not box_center_inside_mask(clamped_box, allowed_plate_mask):
            accepted = False
            reject_reason = "center_outside_plate"
        elif fraction_inside < MIN_BOX_FRACTION_INSIDE_PLATE:
            accepted = False
            reject_reason = "box_mostly_outside_plate"

        if accepted and len(final_colonies) >= TOO_MANY_TO_COUNT_LIMIT:
            too_many_to_count = True
            debug_rows.append(detection_debug_row(
                filename,
                detection_id,
                False,
                "stopped_after_300",
                clamped_box,
                confidence,
                fraction_inside,
            ))
            break

        if accepted:
            final_colonies.append({
                "box": clamped_box,
                "confidence": float(confidence),
                "fraction_inside_plate": fraction_inside,
            })

        debug_rows.append(detection_debug_row(
            filename,
            detection_id,
            accepted,
            reject_reason,
            clamped_box,
            confidence,
            fraction_inside,
        ))

    raw_colony_count = TOO_MANY_TO_COUNT_LIMIT + 1 if too_many_to_count else len(final_colonies)
    colony_count = "Too many to count" if too_many_to_count else raw_colony_count

    cv2.circle(output_image, (plate_x, plate_y), plate_r, (255, 0, 0), 3)
    cv2.circle(output_image, (plate_x, plate_y), inner_radius, (255, 255, 0), 2)

    for colony in final_colonies:
        x1, y1, x2, y2 = colony["box"]
        cx, cy = box_center(colony["box"])
        cv2.rectangle(output_image, (x1, y1), (x2, y2), (0, 180, 0), 2)
        cv2.circle(output_image, (cx, cy), 2, (0, 0, 255), 3)

    text = f"Too many to count (>{TOO_MANY_TO_COUNT_LIMIT})" if too_many_to_count else f"Colony Count: {colony_count}"
    cropped_output, crop_box = crop_around_plate(output_image, plate_x, plate_y, plate_r)
    draw_count_text(cropped_output, text)

    os.makedirs(output_dir, exist_ok=True)
    output_filename = output_filename or f"{os.path.splitext(filename)[0]}_colonies_counted.png"
    output_path = os.path.join(output_dir, output_filename)
    cv2.imwrite(output_path, cropped_output)
    print(f"  - Count result: {colony_count}")
    print(f"  - Saved annotated image to: {output_path}")

    colonies_debug_csv_path = ""
    diagnostics_path = ""
    if save_diagnostics:
        diagnostics_path = diagnostic_dir or os.path.join(output_dir, "diagnostics", os.path.splitext(filename)[0])
        os.makedirs(diagnostics_path, exist_ok=True)
        cv2.imwrite(os.path.join(diagnostics_path, "01_plate_mask.png"), allowed_plate_mask)
        cv2.imwrite(os.path.join(diagnostics_path, "02_masked_yolo_input.png"), masked_image)
        cv2.imwrite(os.path.join(diagnostics_path, "03_final_overlay.png"), cropped_output)
        colonies_debug_csv_path = os.path.join(diagnostics_path, "yolo_detections_debug.csv")
        write_yolo_debug_csv(colonies_debug_csv_path, debug_rows)

    if return_details:
        return {
            "Filename": filename,
            "Colony_Count": colony_count,
            "Raw_Colony_Count": raw_colony_count,
            "Too_Many_To_Count": too_many_to_count,
            "Too_Many_To_Count_Limit": TOO_MANY_TO_COUNT_LIMIT,
            "Count_Stopped_Early": too_many_to_count,
            "Output_Path": output_path,
            "Crop_Box_px": crop_box,
            "Detection_Sensitivity": sensitivity,
            "Colony_Size": colony_size,
            "Split_Touching": bool(split_touching),
            "Detected_Polarity": "YOLO masked plate",
            "Auto_Threshold": float(round(conf, 4)),
            "Threshold_Sweep": "",
            "Accepted_Threshold_Components": raw_colony_count,
            "Binary_Threshold": binary_threshold,
            "Erosion_Iterations": erosion_iterations,
            "Min_Solidity": min_solidity,
            "Min_Colony_Area": min_colony_area,
            "Max_Colony_Area": max_colony_area,
            "Diagnostics_Path": diagnostics_path,
            "Colonies_Debug_CSV": colonies_debug_csv_path,
        }
    return filename, colony_count


def main():
    if len(sys.argv) < 2:
        print("Usage: python count_colonies_yolo.py path/to/image.jpg")
        return
    output_dir = os.path.join(PROJECT_DIR, "yolo_test_output")
    result = process_image(
        sys.argv[1],
        output_dir,
        return_details=True,
        save_diagnostics=True,
    )
    print(result)


if __name__ == "__main__":
    main()
