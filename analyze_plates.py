# analyze_plates.py
import cv2
import numpy as np
import pandas as pd
import os

# =================================================================================
# --- CONFIGURATION & SENSITIVITY SETTINGS ---
# =================================================================================

# --- CORE MEASUREMENT ---
# Set the known physical diameter of your petri dishes in centimeters.
KNOWN_PLATE_DIAMETER_CM = 10.0


# --- PRIMARY CONTROLS (Tune in this order) ---

# CONTROL 1: GROWTH DETECTION THRESHOLD
# What it does: This is your primary control. After contrast enhancement, any pixel BRIGHTER than this value is considered growth.
# How to tune: If the program is measuring too much, INCREASE this value (e.g., from 35 to 40 or 45).
#              If the program is measuring too little, DECREASE this value (e.g., to 30 or 25).
GROWTH_DETECTION_THRESHOLD = 43

# CONTROL 2: MEDIAN BLUR DENOISING
# What it does: Removes fine scratches and "salt-and-pepper" noise BEFORE contrast enhancement. This is critical for clean results.
# How to tune: This must be a small, ODD number (e.g., 3, 5, 7). If your plates are very scratched, use 7 or 9.
MEDIAN_BLUR_SIZE = 7

# CONTROL 3: MAX CENTER DEVIATION PERCENT
# What it does: Defines an internal search zone to ignore edge noise. The program will only measure growth whose center falls inside this zone.
# How to tune: A good starting value is 0.3 (30% of the plate's radius).
MAX_CENTER_DEVIATION_PERCENT = 0.3

# CONTROL 4: MORPHOLOGICAL CLOSING
# What it does: Bridges gaps between separate rings of growth.
# How to tune: If rings aren't connecting, INCREASE this value (e.g., from 46 to 55).
MORPH_CLOSE_KERNEL_SIZE = 46


# --- ADVANCED CONTROLS ---

# ADVANCED CONTROL: CONTRAST (CLAHE)
# How to tune: Default is usually good. For very faint growth, increase clipLimit to 3.0 or 4.0.
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_GRID_SIZE = (8, 8)

# ADVANCED CONTROL: PLATE DETECTION (HOUGH CIRCLES)
# How to tune: Only change if the green circle is wrong. Adjust minRadius/maxRadius for your image resolution.
HOUGH_PARAMS = {
    'dp': 1.2, 'minDist': 150, 'param1': 50, 'param2': 40, 'minRadius': 350, 'maxRadius': 500
}


# --- FOLDER PATHS ---
INPUT_DIR = 'images'
OUTPUT_DIR = 'output'
SUPPORTED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp')
AUTO_SENSITIVITY_LEVELS = {
    'Conservative': 5.00,
    'Normal': 1.75,
    'Sensitive': -1.25,
}

# =================================================================================
# --- Main Program (No changes needed below this line) ---
# =================================================================================

def auto_analyze_agar_plate(
    image_path,
    output_dir,
    plate_diameter_cm=KNOWN_PLATE_DIAMETER_CM,
    sensitivity='Normal',
    hough_params=None,
    output_filename=None,
    save_output=True,
    return_image=False,
):
    filename = os.path.basename(image_path)
    hough_params = hough_params or HOUGH_PARAMS

    image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        print(f"  - ERROR: Could not load image {filename}.")
        return None

    blurred_for_circles = cv2.GaussianBlur(image, (11, 11), 0)
    circles = cv2.HoughCircles(blurred_for_circles, cv2.HOUGH_GRADIENT, **hough_params)
    if circles is None:
        print(f"  - FAILED: No petri dish circle detected in {filename}.")
        return None

    plate_x, plate_y, plate_r = np.round(circles[0, 0]).astype("int")
    pixel_to_cm_ratio = (plate_r * 2) / plate_diameter_cm
    print(f"  - Plate detected. Ratio: {pixel_to_cm_ratio:.2f} px/cm")

    k = AUTO_SENSITIVITY_LEVELS.get(str(sensitivity), AUTO_SENSITIVITY_LEVELS['Normal'])
    if isinstance(sensitivity, (int, float)):
        slider_value = min(100.0, max(0.0, float(sensitivity)))
        conservative = AUTO_SENSITIVITY_LEVELS['Conservative']
        normal = AUTO_SENSITIVITY_LEVELS['Normal']
        sensitive = AUTO_SENSITIVITY_LEVELS['Sensitive']
        if slider_value <= 50:
            k = conservative + (normal - conservative) * (slider_value / 50.0)
        else:
            k = normal + (sensitive - normal) * ((slider_value - 50.0) / 50.0)

    full_plate_mask = np.zeros_like(image, dtype=np.uint8)
    cv2.circle(full_plate_mask, (plate_x, plate_y), plate_r, 255, -1)
    inner_plate_mask = np.zeros_like(image, dtype=np.uint8)
    cv2.circle(inner_plate_mask, (plate_x, plate_y), int(plate_r * 0.90), 255, -1)

    image_float = image.astype(np.float32)
    background_sigma = max(25, plate_r / 5)
    background = cv2.GaussianBlur(image_float, (0, 0), background_sigma)
    normalized = image_float - background

    background_sample_mask = np.zeros_like(image, dtype=np.uint8)
    cv2.circle(background_sample_mask, (plate_x, plate_y), int(plate_r * 0.85), 255, -1)
    cv2.circle(background_sample_mask, (plate_x, plate_y), int(plate_r * 0.45), 0, -1)
    background_values = normalized[background_sample_mask > 0]
    if background_values.size < 1000:
        background_values = normalized[inner_plate_mask > 0]

    background_median = float(np.median(background_values))
    mad = float(np.median(np.abs(background_values - background_median)))
    robust_std = max(1.0, 1.4826 * mad)
    threshold = background_median + (k * robust_std)
    print(f"  - Auto threshold: background + {k:.2f} std ({threshold:.2f})")

    growth_mask = np.zeros_like(image, dtype=np.uint8)
    growth_mask[(normalized > threshold) & (inner_plate_mask > 0)] = 255

    open_size = max(3, int(plate_r * 0.008))
    close_size = max(9, int(plate_r * 0.045))
    open_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_size, open_size))
    close_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size))
    growth_mask = cv2.morphologyEx(growth_mask, cv2.MORPH_OPEN, open_kernel)
    growth_mask = cv2.morphologyEx(growth_mask, cv2.MORPH_CLOSE, close_kernel)

    contours, _ = cv2.findContours(growth_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        print("  - FAILED: No contours detected after auto processing.")
        return None

    valid_contours = []
    max_deviation_pixels = plate_r * 0.38
    min_area = np.pi * (plate_r * 0.025) ** 2
    for contour in contours:
        if len(contour) < 5:
            continue
        if cv2.contourArea(contour) < min_area:
            continue
        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue
        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
        distance = np.sqrt((cx - plate_x) ** 2 + (cy - plate_y) ** 2)
        if distance <= max_deviation_pixels:
            valid_contours.append(contour)

    if not valid_contours:
        print("  - FAILED: No central growth found after auto processing.")
        return None

    main_contour = max(valid_contours, key=cv2.contourArea)
    ellipse = cv2.fitEllipse(main_contour)
    (center_ellipse, axes, angle) = ellipse
    min_axis_pixels, max_axis_pixels = axes

    output_image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    cv2.circle(output_image, (plate_x, plate_y), plate_r, (0, 255, 0), 4)
    cv2.drawContours(output_image, [main_contour], -1, (0, 255, 255), 2)
    cv2.ellipse(output_image, ellipse, (0, 0, 255), 3)

    r_max = max_axis_pixels / 2
    r_min = min_axis_pixels / 2
    angle_rad = np.deg2rad(angle)
    max_p1 = (
        int(center_ellipse[0] - r_max * np.sin(angle_rad)),
        int(center_ellipse[1] + r_max * np.cos(angle_rad))
    )
    max_p2 = (
        int(center_ellipse[0] + r_max * np.sin(angle_rad)),
        int(center_ellipse[1] - r_max * np.cos(angle_rad))
    )
    min_p1 = (
        int(center_ellipse[0] - r_min * np.cos(angle_rad)),
        int(center_ellipse[1] - r_min * np.sin(angle_rad))
    )
    min_p2 = (
        int(center_ellipse[0] + r_min * np.cos(angle_rad)),
        int(center_ellipse[1] + r_min * np.sin(angle_rad))
    )
    cv2.line(output_image, max_p1, max_p2, (255, 0, 0), 2)
    cv2.line(output_image, min_p1, min_p2, (0, 0, 255), 2)

    max_diam_cm = max_axis_pixels / pixel_to_cm_ratio
    min_diam_cm = min_axis_pixels / pixel_to_cm_ratio
    area_cm2 = np.pi * (max_diam_cm / 2) * (min_diam_cm / 2)
    print(f"  - SUCCESS: Max Diameter: {max_diam_cm:.2f} cm, Min Diameter: {min_diam_cm:.2f} cm")

    text_center = (int(center_ellipse[0]), int(center_ellipse[1]))
    cv2.putText(output_image, f"Max: {max_diam_cm:.2f} cm", (text_center[0] - 60, text_center[1] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(output_image, f"Min: {min_diam_cm:.2f} cm", (text_center[0] - 60, text_center[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    y_start, y_end = max(0, plate_y - plate_r), min(output_image.shape[0], plate_y + plate_r)
    x_start, x_end = max(0, plate_x - plate_r), min(output_image.shape[1], plate_x + plate_r)
    cropped_output = output_image[y_start:y_end, x_start:x_end]
    ellipse_points = cv2.ellipse2Poly(
        (int(center_ellipse[0]), int(center_ellipse[1])),
        (max(1, int(max_axis_pixels / 2)), max(1, int(min_axis_pixels / 2))),
        int(angle),
        0,
        360,
        5,
    )
    ellipse_x, ellipse_y, ellipse_w, ellipse_h = cv2.boundingRect(ellipse_points)
    ellipse_bbox = [
        float(ellipse_x - x_start),
        float(ellipse_y - y_start),
        float(ellipse_x + ellipse_w - x_start),
        float(ellipse_y + ellipse_h - y_start),
    ]

    output_path = ""
    if save_output:
        output_path = os.path.join(output_dir, output_filename or f"analyzed_{filename}")
        cv2.imwrite(output_path, cropped_output)

    result = {
        'Filename': filename,
        'Method': 'Auto',
        'Sensitivity': str(sensitivity),
        'Max_Diameter_cm': float(round(max_diam_cm, 2)),
        'Min_Diameter_cm': float(round(min_diam_cm, 2)),
        'Area_cm2': float(round(area_cm2, 2)),
        'Pixel_to_CM_Ratio': float(round(pixel_to_cm_ratio, 2)),
        'Ellipse_BBox_px': ellipse_bbox,
        'Crop_Box_px': [int(x_start), int(y_start), int(x_end), int(y_end)],
        'Output_Path': output_path,
    }
    if return_image:
        result['Annotated_Image'] = cropped_output
    return result

def analyze_agar_plate(
    image_path,
    output_dir,
    plate_diameter_cm=KNOWN_PLATE_DIAMETER_CM,
    growth_threshold=GROWTH_DETECTION_THRESHOLD,
    median_blur_size=MEDIAN_BLUR_SIZE,
    max_center_deviation_percent=MAX_CENTER_DEVIATION_PERCENT,
    morph_close_kernel_size=MORPH_CLOSE_KERNEL_SIZE,
    clahe_clip_limit=CLAHE_CLIP_LIMIT,
    clahe_tile_grid_size=CLAHE_TILE_GRID_SIZE,
    hough_params=None,
    output_filename=None,
    save_output=True,
    return_image=False,
):
    filename = os.path.basename(image_path)
    hough_params = hough_params or HOUGH_PARAMS

    image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        print(f"  - ERROR: Could not load image {filename}.")
        return None
    
    # --- 1. DETECT PETRI DISH AND CALIBRATE ---
    blurred_for_circles = cv2.GaussianBlur(image, (11, 11), 0)
    circles = cv2.HoughCircles(blurred_for_circles, cv2.HOUGH_GRADIENT, **hough_params)

    if circles is None:
        print(f"  - FAILED: No petri dish circle detected in {filename}.")
        return None

    plate_x, plate_y, plate_r = np.round(circles[0, 0]).astype("int")
    pixel_to_cm_ratio = (plate_r * 2) / plate_diameter_cm
    print(f"  - Plate detected. Ratio: {pixel_to_cm_ratio:.2f} px/cm")

    # --- 2. PROCESS FULL PLATE IMAGE ---
    full_plate_mask = np.zeros_like(image)
    cv2.circle(full_plate_mask, (plate_x, plate_y), plate_r, 255, -1)
    masked_image = cv2.bitwise_and(image, image, mask=full_plate_mask)
    
    denoised_image = cv2.medianBlur(masked_image, median_blur_size)
    
    clahe = cv2.createCLAHE(clipLimit=clahe_clip_limit, tileGridSize=clahe_tile_grid_size)
    contrast_enhanced_image = clahe.apply(denoised_image)
    
    _, thresh = cv2.threshold(contrast_enhanced_image, growth_threshold, 255, cv2.THRESH_BINARY)
    print(f"  - Growth Detection Threshold Applied: {growth_threshold}")
    
    kernel = np.ones((morph_close_kernel_size, morph_close_kernel_size), np.uint8)
    closed_thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    
    # --- 3. FIND, FILTER, AND FIT ELLIPSE TO CONTOUR ---
    contours, _ = cv2.findContours(closed_thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        print(f"  - FAILED: No contours detected after processing.")
        return None

    valid_contours = []
    max_deviation_pixels = plate_r * max_center_deviation_percent
    for c in contours:
        if len(c) < 5: continue
        M = cv2.moments(c)
        if M["m00"] == 0: continue
        cx, cy = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        distance = np.sqrt((cx - plate_x)**2 + (cy - plate_y)**2)
        if distance <= max_deviation_pixels:
            valid_contours.append(c)
            
    if not valid_contours:
        print(f"  - FAILED: No growth found within the central search zone.")
        return None
        
    main_contour = max(valid_contours, key=cv2.contourArea)

    # --- 4. CALCULATE DIAMETERS AND PREPARE OUTPUT IMAGE ---
    ellipse = cv2.fitEllipse(main_contour)
    
    (center_ellipse, axes, angle) = ellipse
    min_axis_pixels, max_axis_pixels = axes
    
    output_image = cv2.cvtColor(contrast_enhanced_image, cv2.COLOR_GRAY2BGR)
    
    cv2.circle(output_image, (plate_x, plate_y), plate_r, (0, 255, 0), 4)
    
    cv2.ellipse(output_image, ellipse, (0, 0, 255), 3)

    # ####################################################################
    # ## NEW LOGIC TO DRAW DIAMETER LINES ##
    # ####################################################################
    # Get the radii (half the diameter)
    r_max = max_axis_pixels / 2
    r_min = min_axis_pixels / 2
    
    # Get the angle in radians
    angle_rad = np.deg2rad(angle)
    
    # Calculate endpoints for the major axis (max diameter)
    max_p1 = (
        int(center_ellipse[0] - r_max * np.sin(angle_rad)),
        int(center_ellipse[1] + r_max * np.cos(angle_rad))
    )
    max_p2 = (
        int(center_ellipse[0] + r_max * np.sin(angle_rad)),
        int(center_ellipse[1] - r_max * np.cos(angle_rad))
    )
    cv2.line(output_image, max_p1, max_p2, (255, 0, 0), 2) # Blue line for Max Diameter

    # Calculate endpoints for the minor axis (min diameter)
    min_p1 = (
        int(center_ellipse[0] - r_min * np.cos(angle_rad)),
        int(center_ellipse[1] - r_min * np.sin(angle_rad))
    )
    min_p2 = (
        int(center_ellipse[0] + r_min * np.cos(angle_rad)),
        int(center_ellipse[1] + r_min * np.sin(angle_rad))
    )
    cv2.line(output_image, min_p1, min_p2, (0, 0, 255), 2) # Red line for Min Diameter

    # --- 5. CONVERT TO CM AND SAVE ---
    max_diam_cm = max_axis_pixels / pixel_to_cm_ratio
    min_diam_cm = min_axis_pixels / pixel_to_cm_ratio
    area_cm2 = np.pi * (max_diam_cm / 2) * (min_diam_cm / 2)
    print(f"  - SUCCESS: Max Diameter: {max_diam_cm:.2f} cm, Min Diameter: {min_diam_cm:.2f} cm")

    text_center = (int(center_ellipse[0]), int(center_ellipse[1]))
    cv2.putText(output_image, f"Max: {max_diam_cm:.2f} cm", (text_center[0] - 50, text_center[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(output_image, f"Min: {min_diam_cm:.2f} cm", (text_center[0] - 50, text_center[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    y_start, y_end = max(0, plate_y - plate_r), min(output_image.shape[0], plate_y + plate_r)
    x_start, x_end = max(0, plate_x - plate_r), min(output_image.shape[1], plate_x + plate_r)
    cropped_output = output_image[y_start:y_end, x_start:x_end]
    ellipse_points = cv2.ellipse2Poly(
        (int(center_ellipse[0]), int(center_ellipse[1])),
        (max(1, int(max_axis_pixels / 2)), max(1, int(min_axis_pixels / 2))),
        int(angle),
        0,
        360,
        5,
    )
    ellipse_x, ellipse_y, ellipse_w, ellipse_h = cv2.boundingRect(ellipse_points)
    ellipse_bbox = [
        float(ellipse_x - x_start),
        float(ellipse_y - y_start),
        float(ellipse_x + ellipse_w - x_start),
        float(ellipse_y + ellipse_h - y_start),
    ]

    output_path = ""
    if save_output:
        output_path = os.path.join(output_dir, output_filename or f"analyzed_{filename}")
        cv2.imwrite(output_path, cropped_output)

    result = {
        'Filename': filename,
        'Max_Diameter_cm': float(round(max_diam_cm, 2)),
        'Min_Diameter_cm': float(round(min_diam_cm, 2)),
        'Area_cm2': float(round(area_cm2, 2)),
        'Pixel_to_CM_Ratio': float(round(pixel_to_cm_ratio, 2)),
        'Ellipse_BBox_px': ellipse_bbox,
        'Crop_Box_px': [int(x_start), int(y_start), int(x_end), int(y_end)],
        'Output_Path': output_path,
    }
    if return_image:
        result['Annotated_Image'] = cropped_output
    return result

def find_image_paths(input_dir):
    image_paths = []
    for root, _, files in os.walk(input_dir):
        for file_name in files:
            if file_name.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS):
                image_paths.append(os.path.join(root, file_name))
    return sorted(image_paths)

if __name__ == "__main__":
    if not os.path.exists(OUTPUT_DIR): os.makedirs(OUTPUT_DIR)
    all_results = []
    print(f"--- Starting Agar Plate Analysis ---\nLooking for images in '{INPUT_DIR}' folder...\nPhysical plate diameter set to: {KNOWN_PLATE_DIAMETER_CM} cm")
    
    for path in find_image_paths(INPUT_DIR):
        print(f"\nProcessing {os.path.basename(path)}...")
        result = analyze_agar_plate(path, OUTPUT_DIR)
        if result: all_results.append(result)
            
    if not all_results:
        print("\nAnalysis complete, but no data was generated. Check for errors above.")
    else:
        df = pd.DataFrame(all_results)
        spreadsheet_path = os.path.join(OUTPUT_DIR, 'growth_analysis_results.csv')
        df.to_csv(spreadsheet_path, index=False)
        print(f"\n--- Analysis Complete! ---\nSuccessfully analyzed {len(all_results)} images.\nResults spreadsheet saved to: '{spreadsheet_path}'\nAnnotated images saved in the '{OUTPUT_DIR}' folder.")
