import cv2
import numpy as np
import os
import csv

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

# ------------------------------------

def create_output_directory(output_dir):
    """Creates the output directory if it doesn't exist."""
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        print(f"Created directory: {output_dir}")

def process_image(
    image_path,
    output_dir,
    binary_threshold=BINARY_THRESHOLD,
    erosion_iterations=EROSION_ITERATIONS,
    min_solidity=MIN_SOLIDITY,
    min_colony_area=MIN_COLONY_AREA,
    max_colony_area=MAX_COLONY_AREA,
    output_filename=None,
    return_details=False,
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
    blurred_for_plate = cv2.GaussianBlur(gray_image, (15, 15), 0)
    plate_circles = cv2.HoughCircles(
        blurred_for_plate, cv2.HOUGH_GRADIENT, dp=1.2,
        minDist=int(gray_image.shape[0] * 0.8),
        param1=50, param2=30, minRadius=350, maxRadius=500
    )

    if plate_circles is None:
        print(f"  - No agar plate detected in {filename}.")
        # ... (error handling code remains the same)
        if return_details:
            return None
        return filename, 0

    # Step 2: Store plate parameters and create a mask
    plate_x, plate_y, plate_r = np.round(plate_circles[0, 0]).astype("int")
    cv2.circle(output_image, (plate_x, plate_y), plate_r, (255, 0, 0), 3)

    mask = np.zeros_like(gray_image)
    cv2.circle(mask, (plate_x, plate_y), plate_r, 255, -1)
    masked_image = cv2.bitwise_and(gray_image, gray_image, mask=mask)

    # Step 3: Binarize and Erode to find colony candidates
    _, thresh = cv2.threshold(masked_image, binary_threshold, 255, cv2.THRESH_BINARY)
    kernel = np.ones((3, 3), np.uint8)
    eroded_image = cv2.erode(thresh, kernel, iterations=erosion_iterations)
    contours, _ = cv2.findContours(eroded_image, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidate_colonies = []
    for cnt in contours:
        area = cv2.contourArea(cnt)

        # Step 4: Filter by Area AND Solidity
        if min_colony_area < area < max_colony_area:
            hull = cv2.convexHull(cnt)
            hull_area = cv2.contourArea(hull)
            if hull_area == 0: continue

            solidity = float(area) / hull_area
            if solidity > min_solidity:
                (cx, cy), radius = cv2.minEnclosingCircle(cnt)
                candidate_colonies.append(((int(cx), int(cy)), int(radius)))

    # Step 5: Final Boundary Check
    final_colonies = []
    for center, radius in candidate_colonies:
        dist = np.sqrt((center[0] - plate_x)**2 + (center[1] - plate_y)**2)
        if dist + radius < plate_r:
            final_colonies.append((center, radius))

    colony_count = len(final_colonies)
    print(f"  - Found {colony_count} valid colonies after all filters.")

    # Step 6: Draw final colonies and count
    for center, radius in final_colonies:
        cv2.circle(output_image, center, radius, (0, 255, 0), 2)
        cv2.circle(output_image, center, 2, (0, 0, 255), 3)

    text = f"Colony Count: {colony_count}"
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1
    font_thickness = 2
    text_size = cv2.getTextSize(text, font, font_scale, font_thickness)[0]
    text_x = output_image.shape[1] - text_size[0] - 20
    text_y = output_image.shape[0] - 20
    cv2.putText(output_image, text, (text_x, text_y), font, font_scale, (255, 255, 255), font_thickness)

    # Step 7: Save the annotated image
    output_filename = output_filename or f"{os.path.splitext(filename)[0]}_colonies_counted.png"
    output_path = os.path.join(output_dir, output_filename)
    cv2.imwrite(output_path, output_image)
    print(f"  - Saved annotated image to: {output_path}")

    if return_details:
        return {
            "Filename": filename,
            "Colony_Count": colony_count,
            "Output_Path": output_path,
            "Binary_Threshold": binary_threshold,
            "Erosion_Iterations": erosion_iterations,
            "Min_Solidity": min_solidity,
            "Min_Colony_Area": min_colony_area,
            "Max_Colony_Area": max_colony_area,
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
