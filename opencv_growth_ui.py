import argparse
import csv
import os
import subprocess
import sys
import time

import cv2
import numpy as np

import analyze_plates as analyzer


WINDOW_NAME = "Swim Diameter Analyzer"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
CANVAS_W = 1280
CANVAS_H = 860
PANEL_W = 390


class OpenCVGrowthUI:
    def __init__(self, initial_paths=None):
        self.image_paths = []
        self.index = 0
        self.results = {}
        self.last_settings = None
        self.last_display = None
        self.last_message = "Press O to choose a folder or I to choose images."
        self.last_message_time = time.time()
        self.running = True

        cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_NAME, CANVAS_W, CANVAS_H)
        self._create_trackbars()

        if initial_paths:
            self.add_paths(initial_paths)

    def _create_trackbars(self):
        cv2.createTrackbar("Threshold", WINDOW_NAME, analyzer.GROWTH_DETECTION_THRESHOLD, 255, self._trackbar_changed)
        cv2.createTrackbar("Blur odd index", WINDOW_NAME, 3, 5, self._trackbar_changed)
        cv2.createTrackbar("Search zone %", WINDOW_NAME, int(analyzer.MAX_CENTER_DEVIATION_PERCENT * 100), 80, self._trackbar_changed)
        cv2.createTrackbar("Gap closing", WINDOW_NAME, analyzer.MORPH_CLOSE_KERNEL_SIZE, 140, self._trackbar_changed)
        cv2.createTrackbar("Contrast x10", WINDOW_NAME, int(analyzer.CLAHE_CLIP_LIMIT * 10), 500, self._trackbar_changed)
        cv2.createTrackbar("Plate cm x10", WINDOW_NAME, int(analyzer.KNOWN_PLATE_DIAMETER_CM * 10), 300, self._trackbar_changed)

    def _trackbar_changed(self, _value=None):
        self.last_settings = None

    def run(self):
        while self.running:
            self.render()
            key = cv2.waitKey(80) & 0xFF
            self.handle_key(key)
        cv2.destroyAllWindows()

    def handle_key(self, key):
        if key in (ord("q"), 27):
            self.running = False
        elif key == ord("o"):
            folder = choose_folder()
            if folder:
                self.add_paths(analyzer.find_image_paths(folder), replace=True)
        elif key == ord("i"):
            paths = choose_files()
            if paths:
                self.add_paths(paths, replace=True)
        elif key in (ord("n"), 83):
            self.move(1)
        elif key in (ord("p"), 81):
            self.move(-1)
        elif key == ord("r"):
            self.run_batch()
        elif key == ord("s"):
            self.save_current()
        elif key == ord("c"):
            self.clear()

    def add_paths(self, paths, replace=False):
        clean_paths = []
        seen = set()
        for path in paths:
            if not path:
                continue
            if os.path.isdir(path):
                nested_paths = analyzer.find_image_paths(path)
            else:
                nested_paths = [path]
            for nested_path in nested_paths:
                if nested_path in seen:
                    continue
                if nested_path.lower().endswith(analyzer.SUPPORTED_IMAGE_EXTENSIONS):
                    seen.add(nested_path)
                    clean_paths.append(nested_path)

        if replace:
            self.image_paths = []
            self.results = {}
            self.index = 0

        existing = set(self.image_paths)
        added = 0
        for path in sorted(clean_paths):
            if path not in existing:
                self.image_paths.append(path)
                existing.add(path)
                added += 1

        if added:
            self.index = min(self.index, len(self.image_paths) - 1)
            self.last_settings = None
            self.message(f"Loaded {len(self.image_paths)} image(s).")
        else:
            self.message("No supported images were selected.")

    def clear(self):
        self.image_paths = []
        self.results = {}
        self.index = 0
        self.last_settings = None
        self.last_display = None
        self.message("Image list cleared.")

    def move(self, step):
        if not self.image_paths:
            return
        self.index = (self.index + step) % len(self.image_paths)
        self.last_settings = None

    def settings(self):
        threshold = cv2.getTrackbarPos("Threshold", WINDOW_NAME)
        blur_values = [1, 3, 5, 7, 9, 11]
        blur_index = cv2.getTrackbarPos("Blur odd index", WINDOW_NAME)
        blur = blur_values[max(0, min(blur_index, len(blur_values) - 1))]
        search_zone = max(5, cv2.getTrackbarPos("Search zone %", WINDOW_NAME)) / 100.0
        close_kernel = max(1, cv2.getTrackbarPos("Gap closing", WINDOW_NAME))
        contrast = max(1, cv2.getTrackbarPos("Contrast x10", WINDOW_NAME)) / 10.0
        plate_cm = max(1, cv2.getTrackbarPos("Plate cm x10", WINDOW_NAME)) / 10.0
        return {
            "plate_diameter_cm": plate_cm,
            "growth_threshold": threshold,
            "median_blur_size": blur,
            "max_center_deviation_percent": search_zone,
            "morph_close_kernel_size": close_kernel,
            "clahe_clip_limit": contrast,
        }

    def analyze_current(self):
        if not self.image_paths:
            return None
        current_settings = self.settings()
        cache_key = (self.index, tuple(sorted(current_settings.items())))
        if self.last_settings == cache_key and self.last_display is not None:
            return self.last_display

        path = self.image_paths[self.index]
        try:
            result = analyzer.analyze_agar_plate(
                path,
                OUTPUT_DIR,
                save_output=False,
                return_image=True,
                **current_settings,
            )
        except Exception as exc:
            result = {"Status": f"Error: {exc}", "Annotated_Image": None}

        self.last_settings = cache_key
        self.last_display = result
        return result

    def render(self):
        canvas = np.full((CANVAS_H, CANVAS_W, 3), 245, dtype=np.uint8)
        image_area = (CANVAS_W - PANEL_W, CANVAS_H)

        if self.image_paths:
            result = self.analyze_current()
            annotated = result.get("Annotated_Image") if result else None
            if annotated is not None:
                fitted = fit_image(annotated, image_area[0] - 20, image_area[1] - 20)
                y = (CANVAS_H - fitted.shape[0]) // 2
                x = 10 + (image_area[0] - 20 - fitted.shape[1]) // 2
                canvas[y:y + fitted.shape[0], x:x + fitted.shape[1]] = fitted
            else:
                self._draw_center_text(canvas[:, :image_area[0]], "Analysis failed for this image.")
        else:
            self._draw_center_text(canvas[:, :image_area[0]], "No images loaded")

        self._draw_panel(canvas)
        cv2.imshow(WINDOW_NAME, canvas)

    def _draw_panel(self, canvas):
        x0 = CANVAS_W - PANEL_W
        cv2.rectangle(canvas, (x0, 0), (CANVAS_W, CANVAS_H), (34, 39, 48), -1)
        cv2.putText(canvas, "Swim Diameter Analyzer", (x0 + 22, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)

        y = 82
        if self.image_paths:
            path = self.image_paths[self.index]
            result = self.last_display or {}
            lines = [
                f"Image {self.index + 1} of {len(self.image_paths)}",
                shorten(os.path.basename(path), 34),
                "",
                f"Max: {result.get('Max_Diameter_cm', '--')} cm",
                f"Min: {result.get('Min_Diameter_cm', '--')} cm",
                f"Scale: {result.get('Pixel_to_CM_Ratio', '--')} px/cm",
            ]
        else:
            lines = ["No images loaded", "", "Use O or I to begin."]

        for line in lines:
            color = (242, 244, 248) if line else (242, 244, 248)
            if line:
                cv2.putText(canvas, line, (x0 + 24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.54, color, 1, cv2.LINE_AA)
            y += 28

        settings = self.settings()
        y += 14
        cv2.putText(canvas, "Current Settings", (x0 + 24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2)
        y += 32
        setting_lines = [
            f"Plate diameter: {settings['plate_diameter_cm']:.1f} cm",
            f"Threshold: {settings['growth_threshold']}",
            f"Denoise blur: {settings['median_blur_size']}",
            f"Search zone: {settings['max_center_deviation_percent']:.2f}",
            f"Gap closing: {settings['morph_close_kernel_size']}",
            f"Contrast: {settings['clahe_clip_limit']:.1f}",
        ]
        for line in setting_lines:
            cv2.putText(canvas, line, (x0 + 24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (207, 216, 228), 1, cv2.LINE_AA)
            y += 24

        y += 24
        cv2.putText(canvas, "Keys", (x0 + 24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 2)
        y += 32
        key_lines = [
            "O  choose folder",
            "I  choose images",
            "N/P or arrows  next/previous",
            "R  run batch + CSV",
            "S  save current annotated image",
            "C  clear",
            "Q or Esc  quit",
        ]
        for line in key_lines:
            cv2.putText(canvas, line, (x0 + 24, y), cv2.FONT_HERSHEY_SIMPLEX, 0.47, (207, 216, 228), 1, cv2.LINE_AA)
            y += 25

        if time.time() - self.last_message_time < 6:
            wrapped = wrap_text(self.last_message, 34)
            y = CANVAS_H - 88
            cv2.rectangle(canvas, (x0 + 16, y - 24), (CANVAS_W - 16, CANVAS_H - 18), (63, 78, 98), -1)
            for line in wrapped[:2]:
                cv2.putText(canvas, line, (x0 + 28, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
                y += 24

    def _draw_center_text(self, image, text):
        h, w = image.shape[:2]
        cv2.putText(image, text, (max(20, w // 2 - 170), h // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 90, 105), 2, cv2.LINE_AA)

    def run_batch(self):
        if not self.image_paths:
            self.message("Load images before running the batch.")
            return
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        settings = self.settings()
        rows = []
        for index, path in enumerate(self.image_paths):
            self.index = index
            self.last_settings = None
            self.message(f"Analyzing {index + 1} of {len(self.image_paths)}...")
            self.render()
            cv2.waitKey(1)
            output_filename = output_filename_for(index, path)
            result = analyzer.analyze_agar_plate(path, OUTPUT_DIR, output_filename=output_filename, **settings)
            if result:
                result["Source_Path"] = path
                result["Status"] = "Success"
                rows.append(result)
                self.results[path] = result
        if rows:
            csv_path = os.path.join(OUTPUT_DIR, "growth_analysis_results.csv")
            write_csv(csv_path, rows)
            self.message(f"Finished {len(rows)} of {len(self.image_paths)}. Saved CSV and images to output.")
        else:
            self.message("Finished, but no measurements were generated.")
        self.last_settings = None

    def save_current(self):
        if not self.image_paths:
            self.message("No current image to save.")
            return
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        path = self.image_paths[self.index]
        result = analyzer.analyze_agar_plate(
            path,
            OUTPUT_DIR,
            output_filename=output_filename_for(self.index, path),
            **self.settings(),
        )
        if result:
            self.message(f"Saved {os.path.basename(result['Output_Path'])}.")
        else:
            self.message("Could not save this image because analysis failed.")

    def message(self, text):
        self.last_message = text
        self.last_message_time = time.time()


def choose_folder():
    script = 'POSIX path of (choose folder with prompt "Choose a folder of plate images")'
    return run_osascript(script)


def choose_files():
    script = (
        'set selectedFiles to choose file with prompt "Choose plate images" '
        'of type {"public.image"} with multiple selections allowed\n'
        'set output to ""\n'
        'repeat with selectedFile in selectedFiles\n'
        'set output to output & POSIX path of selectedFile & linefeed\n'
        'end repeat\n'
        'return output'
    )
    output = run_osascript(script)
    if not output:
        return []
    return [line.strip() for line in output.splitlines() if line.strip()]


def run_osascript(script):
    try:
        completed = subprocess.run(["osascript", "-e", script], text=True, capture_output=True, check=False)
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def fit_image(image, max_w, max_h):
    h, w = image.shape[:2]
    scale = min(max_w / w, max_h / h)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def output_filename_for(index, path):
    stem, extension = os.path.splitext(os.path.basename(path))
    return f"analyzed_{index + 1:03d}_{stem}{extension}"


def write_csv(path, rows):
    fieldnames = [
        "Filename",
        "Source_Path",
        "Status",
        "Max_Diameter_cm",
        "Min_Diameter_cm",
        "Pixel_to_CM_Ratio",
        "Output_Path",
    ]
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def shorten(text, max_length):
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def wrap_text(text, width):
    words = text.split()
    lines = []
    line = ""
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines or [""]


def parse_args():
    parser = argparse.ArgumentParser(description="Local OpenCV UI for agar swim diameter analysis.")
    parser.add_argument("paths", nargs="*", help="Image files or folders to open at startup.")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    app = OpenCVGrowthUI(args.paths)
    app.run()
