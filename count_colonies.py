import cv2
import numpy as np
import os
import csv
import math

# --- You can adjust these parameters ---

# BINARY_THRESHOLD: How bright a pixel must be to be considered "growth".
# Lowered to be more sensitive to fainter colonies.
# Recommended range: 25-40
BINARY_THRESHOLD = 30

# EROSION_ITERATIONS: How much to "shrink" colonies to separate them.
# Recommended range: 1-2
EROSION_ITERATIONS = 1

# MIN_SOLIDITY: Filters out non-compact shapes/artifacts.
# Recommended range: 0.85-0.95
MIN_SOLIDITY = 0.9

# MIN_COLONY_AREA: Filters out noise. Lowered slightly as a safeguard.
# Recommended range: 15-30
MIN_COLONY_AREA = 15

# MAX_COLONY_AREA: Filters out large artifacts.
# Recommended range: 3000-6000
MAX_COLONY_AREA = 4000
TOO_MANY_TO_COUNT_LIMIT = 300
COLONY_SIZE_PRESETS = {
    "Small": (2, 900),
    "Medium": (4, 4000),
    "Large": (20, 12000),
    "Mixed": (2, 12000),
}

# ------------------------------------

def create_output_directory(output_dir):
    """Creates the output directory if it doesn't exist."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")


def normalize_to_uint8(image, mask=None):
    values = image[mask > 0] if mask is not None else image.reshape(-1)
    if values.size == 0:
        values = image.reshape(-1)
    low, high = np.percentile(values, (1, 99))
    if high <= low:
        high = low + 1
    scaled = (image.astype(np.float32) - low) * 255.0 / (high - low)
    return np.clip(scaled, 0, 255).astype(np.uint8)


def label_debug_image(labels):
    label_image = np.zeros(labels.shape, dtype=np.uint8)
    if labels.max() > 0:
        label_image = ((labels.astype(np.float32) / labels.max()) * 255).astype(np.uint8)
    return cv2.applyColorMap(label_image, cv2.COLORMAP_TURBO)


def detect_plate(gray_image):
    height, width = gray_image.shape[:2]
    min_dim = min(height, width)
    scale = min(1.0, 1100.0 / max(height, width))
    small = cv2.resize(gray_image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray_image
    small_height, small_width = small.shape[:2]
    small_min_dim = min(small_height, small_width)
    blurred = cv2.GaussianBlur(small, (15, 15), 0)

    candidates = []
    for param2 in (42, 34, 26, 20):
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=int(small_min_dim * 0.55),
            param1=70,
            param2=param2,
            minRadius=int(small_min_dim * 0.22),
            maxRadius=int(small_min_dim * 0.52),
        )
        if circles is not None:
            candidates.extend(np.round(circles[0]).astype("int"))
            break

    if candidates:
        center_x, center_y = small_width / 2, small_height / 2

        def score(circle):
            x, y, radius = circle
            edge_ok = (
                x - radius > -radius * 0.04
                and y - radius > -radius * 0.04
                and x + radius < small_width + radius * 0.04
                and y + radius < small_height + radius * 0.04
            )
            center_distance = np.sqrt((x - center_x) ** 2 + (y - center_y) ** 2)
            edge_penalty = 0 if edge_ok else small_min_dim
            return radius - (0.18 * center_distance) - edge_penalty

        best = max(candidates, key=score)
        x, y, radius = best
        return int(round(x / scale)), int(round(y / scale)), int(round(radius / scale))

    threshold_value = max(10, int(np.percentile(gray_image, 65)))
    _, foreground = cv2.threshold(gray_image, threshold_value, 255, cv2.THRESH_BINARY)
    close_size = max(15, int(min_dim * 0.04))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    (x, y), radius = cv2.minEnclosingCircle(contour)
    return int(x), int(y), int(radius)


def robust_center_scale(values):
    if values.size == 0:
        return 0.0, 1.0
    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    return median, max(1.0, 1.4826 * mad)


def background_correct(channel, plate_r):
    channel_float = channel.astype(np.float32)
    background_sigma = max(25, plate_r / 6)
    background = cv2.GaussianBlur(channel_float, (0, 0), background_sigma)
    return channel_float - background


def build_colony_signal(original_image, gray_image, inner_mask, plate_r):
    lab = cv2.cvtColor(original_image, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(original_image, cv2.COLOR_BGR2HSV)
    channels = {
        "Gray": gray_image,
        "Blue": original_image[:, :, 0],
        "Green": original_image[:, :, 1],
        "Red": original_image[:, :, 2],
        "Lab-L": lab[:, :, 0],
        "Lab-a": lab[:, :, 1],
        "Lab-b": lab[:, :, 2],
        "HSV-S": hsv[:, :, 1],
        "HSV-V": hsv[:, :, 2],
    }

    candidates = []
    for name, channel in channels.items():
        corrected = background_correct(channel, plate_r)
        for polarity_name, signed in (("bright", corrected), ("dark", -corrected)):
            values = signed[inner_mask > 0]
            center, scale = robust_center_scale(values)
            z_signal = (signed - center) / scale
            tail_score = float(np.percentile(z_signal[inner_mask > 0], 99.5)) if values.size else 0.0
            candidates.append((tail_score, f"{name}-{polarity_name}", z_signal.astype(np.float32), signed))

    candidates.sort(key=lambda item: item[0], reverse=True)
    best = candidates[:3]
    signal_z = np.maximum.reduce([item[2] for item in best])
    display_signal = best[0][3]
    selected = ", ".join(item[1] for item in best)
    return signal_z, display_signal, selected


def component_shape_features(component_mask, signal_z, original_image, plate_x, plate_y, plate_r):
    component_u8 = component_mask.astype(np.uint8)
    area = float(np.count_nonzero(component_u8))
    contours, _ = cv2.findContours(component_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour = max(contours, key=cv2.contourArea) if contours else None
    contour_area = float(cv2.contourArea(contour)) if contour is not None else area
    perimeter = float(cv2.arcLength(contour, True)) if contour is not None else 0.0
    hull_area = 0.0
    if contour is not None and len(contour) >= 3:
        hull = cv2.convexHull(contour)
        hull_area = float(cv2.contourArea(hull))
    x, y, w, h = cv2.boundingRect(component_u8)
    aspect_ratio = float(max(w, h) / max(1, min(w, h)))
    extent = float(area / max(1, w * h))
    circularity = float((4 * math.pi * contour_area) / (perimeter * perimeter)) if perimeter > 0 else 0.0
    solidity = float(contour_area / hull_area) if hull_area > 0 else 0.0
    moments = cv2.moments(component_u8)
    if moments["m00"]:
        cx = float(moments["m10"] / moments["m00"])
        cy = float(moments["m01"] / moments["m00"])
    else:
        ys, xs = np.where(component_u8 > 0)
        cx = float(np.mean(xs)) if xs.size else 0.0
        cy = float(np.mean(ys)) if ys.size else 0.0
    radius = float(math.sqrt(area / math.pi)) if area > 0 else 0.0
    distance_from_center = float(math.sqrt((cx - plate_x) ** 2 + (cy - plate_y) ** 2))
    distance_from_plate_edge = float((plate_r * 0.94) - distance_from_center - radius)
    values = signal_z[component_u8 > 0]
    mean_signal = float(np.mean(values)) if values.size else 0.0
    mean_bgr = original_image[component_u8 > 0].mean(axis=0) if area > 0 else np.array([0.0, 0.0, 0.0])

    return {
        "area": area,
        "perimeter": perimeter,
        "circularity": circularity,
        "solidity": solidity,
        "aspect_ratio": aspect_ratio,
        "extent": extent,
        "x": cx,
        "y": cy,
        "radius": radius,
        "mean_signal": mean_signal,
        "mean_color_B": float(mean_bgr[0]),
        "mean_color_G": float(mean_bgr[1]),
        "mean_color_R": float(mean_bgr[2]),
        "distance_from_plate_edge": distance_from_plate_edge,
        "bbox": (x, y, w, h),
    }


def is_plausible_threshold_component(features, min_area, max_area):
    if features["area"] < max(1.0, min_area * 0.45):
        return False
    if features["area"] > max_area * 14:
        return False
    if features["distance_from_plate_edge"] < -2:
        return False
    if features["aspect_ratio"] > 7.5:
        return False
    if features["circularity"] < 0.08 and features["area"] < max_area * 2.0:
        return False
    if features["solidity"] < 0.22 and features["area"] < max_area * 2.0:
        return False
    return True


def is_plausible_final_colony(features, min_area, max_area):
    if features["area"] < min_area:
        return False
    if features["distance_from_plate_edge"] < -1:
        return False
    if features["aspect_ratio"] > 5.5:
        return False
    if features["area"] <= max_area and features["circularity"] < 0.12:
        return False
    if features["area"] <= max_area and features["solidity"] < 0.35:
        return False
    return True


def build_multithreshold_score_map(signal_z, inner_mask, original_image, plate_x, plate_y, plate_r, min_area, max_area, sensitivity):
    sensitivity_value = min(100.0, max(0.0, float(sensitivity)))
    center_threshold = 4.9 - (sensitivity_value / 100.0) * 3.8
    low_threshold = max(0.65, center_threshold - 0.95)
    high_threshold = max(low_threshold + 0.25, center_threshold + 1.55)
    threshold_values = np.linspace(low_threshold, high_threshold, 13)
    score_map = np.zeros(signal_z.shape, dtype=np.float32)
    accepted_components = 0
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    for threshold_value in threshold_values:
        candidate_mask = np.zeros(signal_z.shape, dtype=np.uint8)
        candidate_mask[(signal_z > threshold_value) & (inner_mask > 0)] = 255
        if min_area > 3:
            candidate_mask = cv2.morphologyEx(candidate_mask, cv2.MORPH_OPEN, open_kernel)
        component_count, labels, stats, _ = cv2.connectedComponentsWithStats(candidate_mask, 8)
        for label in range(1, component_count):
            area = float(stats[label, cv2.CC_STAT_AREA])
            if area < max(1.0, min_area * 0.45) or area > max_area * 14:
                continue
            component_mask = labels == label
            features = component_shape_features(component_mask, signal_z, original_image, plate_x, plate_y, plate_r)
            if is_plausible_threshold_component(features, min_area, max_area):
                score_map[component_mask] += 1.0
                accepted_components += 1

    score_map /= float(len(threshold_values))
    score_threshold = 0.48 - (sensitivity_value / 100.0) * 0.23
    score_threshold = min(0.55, max(0.18, score_threshold))
    colony_mask = np.zeros(signal_z.shape, dtype=np.uint8)
    colony_mask[(score_map >= score_threshold) & (inner_mask > 0)] = 255
    close_size = 3
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
    colony_mask = cv2.morphologyEx(colony_mask, cv2.MORPH_CLOSE, close_kernel)
    return colony_mask, score_map, threshold_values, score_threshold, accepted_components


def find_component_peaks(component_mask, distance, min_area):
    estimated_radius = max(1.0, math.sqrt(max(1.0, min_area) / math.pi))
    kernel_size = int(max(3, min(13, round(estimated_radius * 2 + 1))))
    if kernel_size % 2 == 0:
        kernel_size += 1
    peak_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    min_peak = max(1.15, estimated_radius * 0.45)
    local_max = (distance == cv2.dilate(distance, peak_kernel)) & (distance >= min_peak) & component_mask
    peak_count, peak_labels, peak_stats, peak_centroids = cv2.connectedComponentsWithStats(local_max.astype(np.uint8), 8)
    peaks = []
    for label in range(1, peak_count):
        if peak_stats[label, cv2.CC_STAT_AREA] < 1:
            continue
        x, y = peak_centroids[label]
        peaks.append((int(round(x)), int(round(y))))
    return peaks, local_max


def split_component_with_watershed(component_mask, distance, signal_z, peaks):
    if len(peaks) < 2:
        return []
    ys, xs = np.where(component_mask)
    if not xs.size:
        return []
    pad = 3
    x0 = max(0, int(xs.min()) - pad)
    x1 = min(component_mask.shape[1], int(xs.max()) + pad + 1)
    y0 = max(0, int(ys.min()) - pad)
    y1 = min(component_mask.shape[0], int(ys.max()) + pad + 1)
    roi_mask = component_mask[y0:y1, x0:x1].astype(np.uint8)
    markers = np.zeros(roi_mask.shape, dtype=np.int32)
    for marker_id, (x, y) in enumerate(peaks, start=2):
        if x0 <= x < x1 and y0 <= y < y1:
            cv2.circle(markers, (x - x0, y - y0), 1, marker_id, -1)
    markers[roi_mask == 0] = 0
    if markers.max() < 3:
        return []
    roi_signal = normalize_to_uint8(signal_z[y0:y1, x0:x1], roi_mask)
    watershed_input = cv2.cvtColor(roi_signal, cv2.COLOR_GRAY2BGR)
    markers = cv2.watershed(watershed_input, markers)
    segments = []
    for marker_id in range(2, int(markers.max()) + 1):
        segment_roi = (markers == marker_id) & (roi_mask > 0)
        if np.count_nonzero(segment_roi) == 0:
            continue
        segment_mask = np.zeros(component_mask.shape, dtype=bool)
        segment_mask[y0:y1, x0:x1] = segment_roi
        segments.append(segment_mask)
    return segments


def colony_debug_record(filename, colony_id, features, component_was_split, confidence_score, artifact_score):
    return {
        "image": filename,
        "colony_id": colony_id,
        "x": round(features["x"], 2),
        "y": round(features["y"], 2),
        "radius": round(features["radius"], 2),
        "area": round(features["area"], 2),
        "perimeter": round(features["perimeter"], 2),
        "circularity": round(features["circularity"], 3),
        "solidity": round(features["solidity"], 3),
        "aspect_ratio": round(features["aspect_ratio"], 3),
        "mean_intensity": round(features["mean_signal"], 3),
        "mean_color_B": round(features["mean_color_B"], 2),
        "mean_color_G": round(features["mean_color_G"], 2),
        "mean_color_R": round(features["mean_color_R"], 2),
        "distance_from_plate_edge": round(features["distance_from_plate_edge"], 2),
        "component_was_split": bool(component_was_split),
        "artifact_score": round(artifact_score, 3),
        "confidence_score": round(confidence_score, 3),
    }


def write_colonies_debug_csv(path, rows):
    fieldnames = [
        "image",
        "colony_id",
        "x",
        "y",
        "radius",
        "area",
        "perimeter",
        "circularity",
        "solidity",
        "aspect_ratio",
        "mean_intensity",
        "mean_color_B",
        "mean_color_G",
        "mean_color_R",
        "distance_from_plate_edge",
        "component_was_split",
        "artifact_score",
        "confidence_score",
    ]
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def process_image(
    image_path,
    output_dir,
    binary_threshold=BINARY_THRESHOLD,
    erosion_iterations=0,
    min_solidity=MIN_SOLIDITY,
    min_colony_area=MIN_COLONY_AREA,
    max_colony_area=MAX_COLONY_AREA,
    sensitivity=50,
    colony_size="Medium",
    split_touching=True,
    output_filename=None,
    return_details=False,
    save_diagnostics=False,
    diagnostic_dir=None,
):
    """
    Processes a single image to detect colonies, using tuned parameters
    for maximum accuracy on varied colony types.
    """
    filename = os.path.basename(image_path)
    print(f"\nProcessing {filename}...")

    original_image = cv2.imread(image_path)
    if original_image is None:
        print(f"Error: Could not read image at {image_path}")
        if return_details:
            return None
        return filename, 0

    output_image = original_image.copy()
    gray_image = cv2.cvtColor(original_image, cv2.COLOR_BGR2GRAY)

    # Step 1: Detect the agar plate
    plate = detect_plate(gray_image)
    if plate is None:
        print(f"  - No agar plate detected in {filename}.")
        # ... (error handling code remains the same)
        if return_details:
            return None
        return filename, 0

    # Step 2: Store plate parameters and create a mask
    plate_x, plate_y, plate_r = plate
    cv2.circle(output_image, (plate_x, plate_y), plate_r, (255, 0, 0), 3)

    inner_mask = np.zeros_like(gray_image, dtype=np.uint8)
    cv2.circle(inner_mask, (plate_x, plate_y), int(plate_r * 0.92), 255, -1)

    size_min, size_max = COLONY_SIZE_PRESETS.get(str(colony_size), COLONY_SIZE_PRESETS["Medium"])
    min_colony_area = float(size_min)
    max_colony_area = float(size_max)

    # Step 3: Build a colony-enhanced signal from multiple color channels.
    signal_z, display_signal, selected_signal = build_colony_signal(original_image, gray_image, inner_mask, plate_r)

    # Step 4: Sweep thresholds and accumulate only morphologically plausible regions.
    colony_mask, score_map, threshold_values, score_threshold, accepted_components = build_multithreshold_score_map(
        signal_z,
        inner_mask,
        original_image,
        plate_x,
        plate_y,
        plate_r,
        min_colony_area,
        max_colony_area,
        sensitivity,
    )
    threshold_mask = np.zeros_like(gray_image, dtype=np.uint8)
    threshold_mask[(score_map >= score_threshold) & (inner_mask > 0)] = 255

    final_colonies = []
    colony_debug_rows = []
    too_many_to_count = False
    component_count, labels, stats, centroids = cv2.connectedComponentsWithStats(colony_mask, 8)
    distance = cv2.distanceTransform(colony_mask, cv2.DIST_L2, 5)
    local_max = np.zeros_like(gray_image, dtype=bool)

    def add_colony_from_mask(colony_mask_bool, component_was_split):
        nonlocal too_many_to_count
        if too_many_to_count:
            return False
        features = component_shape_features(colony_mask_bool, signal_z, original_image, plate_x, plate_y, plate_r)
        if not is_plausible_final_colony(features, min_colony_area, max_colony_area):
            return False
        if len(final_colonies) >= TOO_MANY_TO_COUNT_LIMIT:
            too_many_to_count = True
            return False
        confidence_score = float(np.mean(score_map[colony_mask_bool])) if np.any(colony_mask_bool) else 0.0
        shape_penalty = 0.0
        if features["aspect_ratio"] > 2.2:
            shape_penalty += min(0.35, (features["aspect_ratio"] - 2.2) / 8)
        if features["circularity"] < 0.45:
            shape_penalty += min(0.35, (0.45 - features["circularity"]) / 0.45)
        if features["solidity"] < 0.65:
            shape_penalty += min(0.25, (0.65 - features["solidity"]) / 0.65)
        if features["distance_from_plate_edge"] < plate_r * 0.025:
            shape_penalty += 0.15
        artifact_score = min(1.0, shape_penalty)
        colony_id = len(final_colonies) + 1
        final_colonies.append({
            "center": (int(round(features["x"])), int(round(features["y"]))),
            "radius": max(2, int(round(features["radius"]))),
            "features": features,
            "confidence_score": confidence_score,
            "artifact_score": artifact_score,
            "component_was_split": bool(component_was_split),
        })
        colony_debug_rows.append(colony_debug_record(
            filename,
            colony_id,
            features,
            component_was_split,
            confidence_score,
            artifact_score,
        ))
        return True

    for label in range(1, component_count):
        if too_many_to_count:
            break
        area = float(stats[label, cv2.CC_STAT_AREA])
        if area < min_colony_area:
            continue
        component_mask = labels == label
        features = component_shape_features(component_mask, signal_z, original_image, plate_x, plate_y, plate_r)
        peaks, component_local_max = find_component_peaks(component_mask, distance, min_colony_area)
        local_max |= component_local_max
        looks_clustered = (
            len(peaks) >= 2
            and (
                area > max_colony_area * 0.85
                or features["circularity"] < 0.55
                or features["aspect_ratio"] > 1.8
            )
        )

        if split_touching and looks_clustered:
            segments = split_component_with_watershed(component_mask, distance, signal_z, peaks)
            accepted_before = len(final_colonies)
            for segment_mask in segments:
                add_colony_from_mask(segment_mask, component_was_split=True)
                if too_many_to_count:
                    break
            if too_many_to_count:
                break
            if len(final_colonies) > accepted_before:
                continue

        if area > max_colony_area * 2.5:
            for x, y in peaks:
                peak_radius = max(2, int(round(distance[y, x])))
                peak_mask = np.zeros_like(gray_image, dtype=np.uint8)
                cv2.circle(peak_mask, (x, y), peak_radius, 255, -1)
                add_colony_from_mask((peak_mask > 0) & component_mask, component_was_split=True)
                if too_many_to_count:
                    break
            continue

        add_colony_from_mask(component_mask, component_was_split=False)

    raw_colony_count = TOO_MANY_TO_COUNT_LIMIT + 1 if too_many_to_count else len(final_colonies)
    colony_count = "Too many to count" if too_many_to_count else raw_colony_count
    count_message = f"more than {TOO_MANY_TO_COUNT_LIMIT}" if too_many_to_count else str(raw_colony_count)
    print(f"  - Found {count_message} valid colonies after all filters.")
    if too_many_to_count:
        print(f"  - Stopped counting and annotating after {TOO_MANY_TO_COUNT_LIMIT}; marked as too many to count.")

    # Step 6: Draw final colonies and count
    for colony in final_colonies:
        center = colony["center"]
        cv2.circle(output_image, center, 2, (0, 0, 255), 3)

    text = f"Colony Count: {colony_count}" if not too_many_to_count else f"Too many to count (>{TOO_MANY_TO_COUNT_LIMIT})"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1
    font_thickness = 2
    text_size = cv2.getTextSize(text, font, font_scale, font_thickness)[0]
    text_x = max(20, output_image.shape[1] - text_size[0] - 20)
    text_y = output_image.shape[0] - 20
    cv2.putText(output_image, text, (text_x, text_y), font, font_scale, (255, 255, 255), font_thickness)

    # Step 7: Save the annotated image
    output_filename = output_filename or f"{os.path.splitext(filename)[0]}_colonies_counted.png"
    output_path = os.path.join(output_dir, output_filename)
    cv2.imwrite(output_path, output_image)
    print(f"  - Saved annotated image to: {output_path}")

    colonies_debug_csv_path = ""
    if save_diagnostics:
        diagnostics_path = diagnostic_dir or os.path.join(output_dir, "diagnostics", os.path.splitext(filename)[0])
        os.makedirs(diagnostics_path, exist_ok=True)
        cv2.imwrite(os.path.join(diagnostics_path, "01_plate_mask.png"), inner_mask)
        cv2.imwrite(os.path.join(diagnostics_path, "02_normalized_signal.png"), normalize_to_uint8(display_signal, inner_mask))
        cv2.imwrite(os.path.join(diagnostics_path, "03_score_map.png"), normalize_to_uint8(score_map, inner_mask))
        cv2.imwrite(os.path.join(diagnostics_path, "04_score_threshold_mask.png"), threshold_mask)
        cv2.imwrite(os.path.join(diagnostics_path, "05_final_colony_mask.png"), colony_mask)
        cv2.imwrite(os.path.join(diagnostics_path, "06_connected_components.png"), label_debug_image(labels))
        local_max_image = np.zeros_like(gray_image, dtype=np.uint8)
        local_max_image[local_max] = 255
        cv2.imwrite(os.path.join(diagnostics_path, "07_local_maxima.png"), local_max_image)
        cv2.imwrite(os.path.join(diagnostics_path, "08_final_overlay.png"), output_image)
        colonies_debug_csv_path = os.path.join(diagnostics_path, "colonies_debug.csv")
        write_colonies_debug_csv(colonies_debug_csv_path, colony_debug_rows)
    else:
        diagnostics_path = ""

    if return_details:
        return {
            "Filename": filename,
            "Colony_Count": colony_count,
            "Raw_Colony_Count": raw_colony_count,
            "Too_Many_To_Count": too_many_to_count,
            "Too_Many_To_Count_Limit": TOO_MANY_TO_COUNT_LIMIT,
            "Count_Stopped_Early": too_many_to_count,
            "Output_Path": output_path,
            "Detection_Sensitivity": sensitivity,
            "Colony_Size": colony_size,
            "Split_Touching": bool(split_touching),
            "Detected_Polarity": selected_signal,
            "Auto_Threshold": float(round(score_threshold, 3)),
            "Threshold_Sweep": f"{float(threshold_values[0]):.2f}-{float(threshold_values[-1]):.2f}",
            "Accepted_Threshold_Components": accepted_components,
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
    """
    Main function to find and process all images in the 'images' folder.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    image_dir = os.path.join(base_dir, "images")
    output_dir = os.path.join(base_dir, "output")

    if not os.path.isdir(image_dir):
        print(f"Error: 'images' directory not found at '{image_dir}'")
        return

    create_output_directory(output_dir)

    supported_formats = ('.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff')
    image_files = [f for f in os.listdir(image_dir) if f.lower().endswith(supported_formats)]

    if not image_files:
        print(f"No images found in the '{image_dir}' directory. Nothing to process.")
        return

    print(f"Found {len(image_files)} image(s) to process.")

    results = []
    for filename in image_files:
        full_image_path = os.path.join(image_dir, filename)
        result_filename, count = process_image(full_image_path, output_dir)
        results.append([result_filename, count])

    if results:
        csv_path = os.path.join(output_dir, "colony_counts.csv")
        with open(csv_path, 'w', newline='') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Filename', 'ColonyCount'])
            writer.writerows(results)
        print(f"\nSuccessfully wrote all results to {csv_path}")

    print("\nProcessing complete.")

if __name__ == "__main__":
    main()
