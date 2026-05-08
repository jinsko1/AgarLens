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
# What it does: Defines a "search zone" (orange circle) to ignore edge noise. The program will only measure growth whose center falls inside this zone.
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

# =================================================================================
# --- Main Program (No changes needed below this line) ---
# =================================================================================

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
    cv2.circle(output_image, (plate_x, plate_y), int(max_deviation_pixels), (0, 165, 255), 2)
    
    cv2.ellipse(output_image, ellipse, (0, 0, 255), 3)

    center_search_radius = int(plate_r * 0.2)
    center_mask = np.zeros_like(image)
    cv2.circle(center_mask, (plate_x, plate_y), center_search_radius, 255, -1)
    _, _, _, max_loc = cv2.minMaxLoc(image, mask=center_mask)
    cv2.circle(output_image, max_loc, 10, (255, 255, 0), 2)

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
    print(f"  - SUCCESS: Max Diameter: {max_diam_cm:.2f} cm, Min Diameter: {min_diam_cm:.2f} cm")

    text_center = (int(center_ellipse[0]), int(center_ellipse[1]))
    cv2.putText(output_image, f"Max: {max_diam_cm:.2f} cm", (text_center[0] - 50, text_center[1] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(output_image, f"Min: {min_diam_cm:.2f} cm", (text_center[0] - 50, text_center[1] + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    y_start, y_end = max(0, plate_y - plate_r), min(output_image.shape[0], plate_y + plate_r)
    x_start, x_end = max(0, plate_x - plate_r), min(output_image.shape[1], plate_x + plate_r)
    cropped_output = output_image[y_start:y_end, x_start:x_end]

    output_path = ""
    if save_output:
        output_path = os.path.join(output_dir, output_filename or f"analyzed_{filename}")
        cv2.imwrite(output_path, cropped_output)

    result = {
        'Filename': filename,
        'Max_Diameter_cm': float(round(max_diam_cm, 2)),
        'Min_Diameter_cm': float(round(min_diam_cm, 2)),
        'Pixel_to_CM_Ratio': float(round(pixel_to_cm_ratio, 2)),
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
