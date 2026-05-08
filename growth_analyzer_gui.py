#!/usr/local/bin/python3

import csv
import json
import os
import queue
import subprocess
import sys
import threading


UI_PYTHON = "/usr/local/bin/python3"
ANALYSIS_PYTHON = "/usr/local/bin/python3"

if not os.environ.get("SWIM_TK_UI_REEXECED") and sys.executable.startswith("/opt/homebrew/"):
    env = os.environ.copy()
    env["SWIM_TK_UI_REEXECED"] = "1"
    os.execve(UI_PYTHON, [UI_PYTHON, os.path.abspath(__file__), *sys.argv[1:]], env)

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Swim Diameter Analyzer"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER_PATH = os.path.join(PROJECT_DIR, "analysis_worker.py")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
PREVIEW_DIR = os.path.join(OUTPUT_DIR, "live_preview")
SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
PREVIEW_DEBOUNCE_MS = 900

SETTING_HELP = {
    "Plate diameter (cm)": "The real width of your agar plate. This converts pixels into centimeters. If this is wrong, every measurement will be scaled wrong.",
    "Growth threshold": "How bright a pixel must be before it counts as growth. Higher values measure only brighter growth. Lower values include fainter growth, but may include background noise.",
    "Denoise blur": "Smooths tiny specks, dust, and scanner scratches before measuring. Larger values clean up noisy images, but can soften small details.",
    "Search zone": "Limits detection to growth near the plate center. Increase this if real growth is off-center. Decrease it if edges or labels are being counted.",
    "Gap closing": "Connects broken rings or gaps in the detected growth area. Increase it when growth looks split apart. Decrease it if separate marks are being merged.",
    "Contrast limit": "Boosts faint growth before measuring. Increase it for pale growth. Decrease it if the background becomes too bright.",
}

DEFAULTS = {
    "plate_diameter_cm": 10.0,
    "growth_threshold": 43,
    "median_blur_size": 7,
    "max_center_deviation_percent": 0.30,
    "morph_close_kernel_size": 46,
    "clahe_clip_limit": 2.0,
}


class InfoButton(tk.Canvas):
    def __init__(self, parent, command):
        super().__init__(parent, width=22, height=22, highlightthickness=0, bd=0)
        self.command = command
        self.configure(cursor="hand2")
        self.bind("<Button-1>", lambda _event: self.command())
        self.bind("<Enter>", lambda _event: self._draw(active=True))
        self.bind("<Leave>", lambda _event: self._draw(active=False))
        self._draw(active=False)

    def _draw(self, active=False):
        self.delete("all")
        color = "#111111" if not active else "#2563eb"
        self.create_oval(2, 2, 20, 20, outline=color, width=2)
        self.create_text(11, 11, text="i", fill=color, font=("Helvetica", 13, "bold"))


class GrowthAnalyzerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1240x780")
        self.root.minsize(980, 640)

        self.image_paths = []
        self.row_paths = {}
        self.results_by_path = {}
        self.event_queue = queue.Queue()
        self.batch_thread = None
        self.preview_thread = None
        self.preview_after_id = None
        self.preview_generation = 0
        self.preview_pending = False
        self.preview_path = None
        self.preview_photo = None

        self.output_dir_var = tk.StringVar(value=OUTPUT_DIR)
        self.plate_diameter_var = tk.DoubleVar(value=DEFAULTS["plate_diameter_cm"])
        self.threshold_var = tk.IntVar(value=DEFAULTS["growth_threshold"])
        self.blur_var = tk.IntVar(value=DEFAULTS["median_blur_size"])
        self.center_zone_var = tk.DoubleVar(value=DEFAULTS["max_center_deviation_percent"])
        self.close_kernel_var = tk.IntVar(value=DEFAULTS["morph_close_kernel_size"])
        self.clahe_var = tk.DoubleVar(value=DEFAULTS["clahe_clip_limit"])

        self._load_theme()
        self._build_ui()
        self._bind_preview_traces()
        self._set_status("Choose a folder or images. Select one row to tune the live preview.")
        self.root.after(100, self._drain_event_queue)

    def _load_theme(self):
        try:
            self.root.tk.call("source", os.path.join(PROJECT_DIR, "azure.tcl"))
            self.root.tk.call("set_theme", "light")
        except tk.TclError:
            pass

    def _build_ui(self):
        self.root.columnconfigure(0, weight=0)
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        controls = ttk.Frame(self.root, padding=(18, 16), width=340)
        controls.grid(row=0, column=0, sticky="ns")
        controls.grid_propagate(False)
        controls.columnconfigure(0, weight=1)

        workspace = ttk.Frame(self.root, padding=(0, 16, 18, 16))
        workspace.grid(row=0, column=1, sticky="nsew")
        workspace.columnconfigure(0, weight=1)
        workspace.rowconfigure(0, weight=3)
        workspace.rowconfigure(1, weight=2)

        self._build_controls(controls)
        self._build_preview(workspace)
        self._build_table(workspace)

    def _build_controls(self, parent):
        ttk.Label(parent, text=APP_TITLE, font=("Helvetica", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(parent, text="Tune one preview, apply settings to the batch").grid(row=1, column=0, sticky="w", pady=(2, 18))

        buttons = ttk.Frame(parent)
        buttons.grid(row=2, column=0, sticky="ew")
        buttons.columnconfigure((0, 1), weight=1)
        ttk.Button(buttons, text="Add Images", command=self.add_images).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(buttons, text="Add Folder", command=self.add_folder).grid(row=0, column=1, sticky="ew", padx=(5, 0))
        ttk.Button(parent, text="Clear List", command=self.clear_images).grid(row=3, column=0, sticky="ew", pady=(8, 16))

        output = ttk.LabelFrame(parent, text="Output", padding=12)
        output.grid(row=4, column=0, sticky="ew", pady=(0, 14))
        output.columnconfigure(0, weight=1)
        ttk.Entry(output, textvariable=self.output_dir_var).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(output, text="Browse", command=self.choose_output_dir).grid(row=0, column=1)

        settings = ttk.LabelFrame(parent, text="Analysis Settings", padding=12)
        settings.grid(row=5, column=0, sticky="ew")
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(1, weight=0)
        self._spin(settings, 0, "Plate diameter (cm)", self.plate_diameter_var, 1.0, 30.0, 0.1)
        self._scale(settings, 2, "Growth threshold", self.threshold_var, 0, 255, integer=True)
        self._blur(settings, 4)
        self._scale(settings, 6, "Search zone", self.center_zone_var, 0.05, 0.80)
        self._spin(settings, 8, "Gap closing", self.close_kernel_var, 1, 140, 1)
        self._spin(settings, 10, "Contrast limit", self.clahe_var, 1.0, 50.0, 0.5)

        self.run_button = ttk.Button(parent, text="Run Batch Analysis", command=self.start_batch_analysis, style="Accent.TButton")
        self.run_button.grid(row=6, column=0, sticky="ew", pady=(18, 8), ipady=4)
        self.reanalyze_button = ttk.Button(parent, text="Reanalyze Selected Image", command=self.reanalyze_selected, state="disabled")
        self.reanalyze_button.grid(row=7, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(parent, text="Open Output Folder", command=self.open_output_dir).grid(row=8, column=0, sticky="ew")

        self.progress = ttk.Progressbar(parent, mode="determinate")
        self.progress.grid(row=9, column=0, sticky="ew", pady=(16, 6))
        self.status_label = ttk.Label(parent, text="", wraplength=300)
        self.status_label.grid(row=10, column=0, sticky="ew")

    def _spin(self, parent, row, label, variable, from_, to, increment):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(0, 4))
        self._info_button(parent, row, label)
        ttk.Spinbox(parent, textvariable=variable, from_=from_, to=to, increment=increment).grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

    def _scale(self, parent, row, label, variable, from_, to, integer=False):
        label_var = tk.StringVar()

        def update_label(*_):
            value = variable.get()
            display_value = str(int(value)) if integer else format(value, ".2f")
            label_var.set(f"{label}: {display_value}")

        variable.trace_add("write", update_label)
        update_label()
        ttk.Label(parent, textvariable=label_var).grid(row=row, column=0, sticky="w", pady=(0, 4))
        self._info_button(parent, row, label)
        ttk.Scale(parent, variable=variable, from_=from_, to=to).grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

    def _blur(self, parent, row):
        ttk.Label(parent, text="Denoise blur").grid(row=row, column=0, sticky="w", pady=(0, 4))
        self._info_button(parent, row, "Denoise blur")
        ttk.Combobox(parent, textvariable=self.blur_var, values=(1, 3, 5, 7, 9, 11), state="readonly").grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

    def _info_button(self, parent, row, label):
        InfoButton(parent, command=lambda: self.show_setting_help(label)).grid(row=row, column=1, sticky="e", padx=(8, 0), pady=(0, 4))

    def show_setting_help(self, label):
        messagebox.showinfo(label, SETTING_HELP.get(label, "This setting changes how the plate image is processed."))

    def _build_preview(self, parent):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=12)
        frame.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        self.preview_title = ttk.Label(header, text="Live Preview", font=("Helvetica", 13, "bold"))
        self.preview_title.grid(row=0, column=0, sticky="w")
        self.preview_status = ttk.Label(header, text="")
        self.preview_status.grid(row=0, column=1, sticky="e")

        self.preview_label = ttk.Label(frame, text="Select a row to tune this image.", anchor="center")
        self.preview_label.grid(row=1, column=0, sticky="nsew")
        self.preview_result = ttk.Label(frame, text="", anchor="center")
        self.preview_result.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_table(self, parent):
        frame = ttk.Frame(parent)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ("file", "status", "max", "min", "ratio", "source")
        self.table = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        headings = {"file": "File", "status": "Status", "max": "Max cm", "min": "Min cm", "ratio": "px/cm", "source": "Source"}
        widths = {"file": 230, "status": 120, "max": 80, "min": 80, "ratio": 80, "source": 380}
        for column in columns:
            self.table.heading(column, text=headings[column])
            self.table.column(column, width=widths[column], anchor="w" if column in ("file", "source") else "center")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=yscroll.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        self.table.bind("<<TreeviewSelect>>", self.on_row_selected)

    def add_images(self):
        paths = filedialog.askopenfilenames(
            title="Select plate images",
            filetypes=(("Image files", " ".join(f"*{ext}" for ext in SUPPORTED_IMAGE_EXTENSIONS)), ("All files", "*.*")),
        )
        self._add_paths(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select image folder")
        if folder:
            self._add_paths(find_image_paths(folder))

    def _add_paths(self, paths):
        if self.is_busy():
            return
        seen = set(self.image_paths)
        added = 0
        for path in sorted(paths):
            if path in seen or not path.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS):
                continue
            seen.add(path)
            self.image_paths.append(path)
            item_id = str(len(self.image_paths) - 1)
            self.row_paths[item_id] = path
            self.table.insert("", "end", iid=item_id, values=(os.path.basename(path), "Ready", "", "", "", path))
            added += 1

        if added:
            if not self.table.selection():
                first_item = self.table.get_children()[0]
                self.table.selection_set(first_item)
                self.table.focus(first_item)
                self.set_preview_path(self.row_paths[first_item])
            self._set_status(f"Loaded {len(self.image_paths)} image(s). Current settings will apply to the whole batch.")
        else:
            self._set_status("No new supported images were added.")

    def clear_images(self):
        if self.is_busy():
            return
        self.image_paths = []
        self.row_paths = {}
        self.results_by_path = {}
        self.preview_path = None
        self.preview_photo = None
        self.preview_generation += 1
        for item in self.table.get_children():
            self.table.delete(item)
        self.preview_title.config(text="Live Preview")
        self.preview_label.config(text="Select a row to tune this image.", image="")
        self.preview_result.config(text="")
        self.preview_status.config(text="")
        self.progress["value"] = 0
        self.reanalyze_button.state(["disabled"])
        self._set_status("Choose a folder or images. Select one row to tune the live preview.")

    def choose_output_dir(self):
        folder = filedialog.askdirectory(title="Select output folder", initialdir=self.output_dir_var.get())
        if folder:
            self.output_dir_var.set(folder)

    def start_batch_analysis(self):
        if self.is_busy():
            return
        if not self.image_paths:
            messagebox.showinfo("No Images", "Add images or a folder first.")
            return
        try:
            settings = self.settings()
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid Settings", "One or more settings is blank or invalid. Please enter a valid number.")
            return
        os.makedirs(self.output_dir_var.get(), exist_ok=True)
        self.progress["maximum"] = len(self.image_paths)
        self.progress["value"] = 0
        self.run_button.state(["disabled"])
        self.reanalyze_button.state(["disabled"])
        self.batch_thread = threading.Thread(target=self._batch_worker, args=(settings,), daemon=True)
        self.batch_thread.start()

    def _batch_worker(self, settings):
        for index, image_path in enumerate(self.image_paths):
            self.event_queue.put(("status", index, "Running"))
            payload = self._analyze_path(index, image_path, settings)
            if payload.get("ok"):
                result = payload["result"]
                result["Source_Path"] = image_path
                result["Status"] = "Success"
                self.event_queue.put(("result", index, result))
            else:
                self.event_queue.put(("status", index, "Failed"))
            self.event_queue.put(("progress", index + 1))
        self.event_queue.put(("batch_done",))

    def reanalyze_selected(self):
        selection = self.table.selection()
        if self.is_busy() or not selection:
            return
        index = int(selection[0])
        image_path = self.row_paths.get(selection[0])
        if not image_path:
            return
        try:
            settings = self.settings()
        except (tk.TclError, ValueError):
            messagebox.showerror("Invalid Settings", "One or more settings is blank or invalid. Please enter a valid number.")
            return
        self.run_button.state(["disabled"])
        self.reanalyze_button.state(["disabled"])
        self.batch_thread = threading.Thread(target=self._reanalyze_worker, args=(index, image_path, settings), daemon=True)
        self.batch_thread.start()

    def _reanalyze_worker(self, index, image_path, settings):
        self.event_queue.put(("status", index, "Reanalyzing"))
        payload = self._analyze_path(index, image_path, settings)
        if payload.get("ok"):
            result = payload["result"]
            result["Source_Path"] = image_path
            result["Status"] = "Reanalyzed"
            self.event_queue.put(("result", index, result))
        else:
            self.event_queue.put(("status", index, "Failed"))
        self.event_queue.put(("reanalyze_done",))

    def _analyze_path(self, index, image_path, settings):
        output_filename = output_filename_for(index, image_path)
        return run_analysis(image_path, self.output_dir_var.get(), output_filename, settings)

    def _drain_event_queue(self):
        try:
            while True:
                event = self.event_queue.get_nowait()
                self.handle_event(event)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_event_queue)

    def handle_event(self, event):
        kind = event[0]
        if kind == "status":
            _, index, status = event
            self.update_row(index, status=status)
        elif kind == "result":
            _, index, result = event
            self.results_by_path[result["Source_Path"]] = result
            self.update_row(index, result["Status"], result["Max_Diameter_cm"], result["Min_Diameter_cm"], result["Pixel_to_CM_Ratio"])
            if result["Source_Path"] == self.preview_path:
                self.apply_preview_payload({"ok": True, "result": result})
            self.write_current_csv()
        elif kind == "progress":
            self.progress["value"] = event[1]
            self._set_status(f"Analyzed {event[1]} of {len(self.image_paths)} image(s).")
        elif kind == "batch_done":
            self.batch_thread = None
            self.run_button.state(["!disabled"])
            self.update_reanalyze_button()
            self._set_status(f"Finished: {len(self.results_by_path)} measured result(s). Select a row and adjust settings to reanalyze it.")
        elif kind == "reanalyze_done":
            self.batch_thread = None
            self.run_button.state(["!disabled"])
            self.update_reanalyze_button()
            self._set_status("Selected image reanalyzed with the current settings.")
        elif kind == "preview_status":
            _, generation, status = event
            if generation == self.preview_generation:
                self.preview_status.config(text=status)
        elif kind == "preview_result":
            _, generation, payload = event
            if generation == self.preview_generation:
                self.apply_preview_payload(payload)
        elif kind == "preview_done":
            _, generation = event
            if generation == self.preview_generation:
                self.preview_thread = None
                self.preview_status.config(text="")
                if self.preview_pending:
                    self.preview_pending = False
                    self.schedule_live_preview(delay=250)

    def update_row(self, index, status=None, max_cm="", min_cm="", ratio=""):
        item_id = str(index)
        if not self.table.exists(item_id):
            return
        values = list(self.table.item(item_id, "values"))
        if status:
            values[1] = status
        values[2], values[3], values[4] = max_cm, min_cm, ratio
        self.table.item(item_id, values=values)

    def on_row_selected(self, _event=None):
        selection = self.table.selection()
        if not selection:
            self.update_reanalyze_button()
            return
        self.set_preview_path(self.row_paths.get(selection[0]))
        self.update_reanalyze_button()

    def set_preview_path(self, path):
        if not path:
            return
        self.preview_path = path
        self.preview_title.config(text=os.path.basename(path))
        self.preview_status.config(text="")
        result = self.results_by_path.get(path)
        if result:
            self.apply_preview_payload({"ok": True, "result": result})
        else:
            self.preview_result.config(text="Live preview updates after settings settle.")
            self.schedule_live_preview(delay=150)

    def _bind_preview_traces(self):
        for variable in (
            self.plate_diameter_var,
            self.threshold_var,
            self.blur_var,
            self.center_zone_var,
            self.close_kernel_var,
            self.clahe_var,
        ):
            variable.trace_add("write", lambda *_: self.schedule_live_preview())

    def schedule_live_preview(self, delay=PREVIEW_DEBOUNCE_MS):
        if not self.preview_path:
            return
        if self.preview_after_id:
            self.root.after_cancel(self.preview_after_id)
        self.preview_after_id = self.root.after(delay, self.start_live_preview)

    def start_live_preview(self):
        self.preview_after_id = None
        if not self.preview_path:
            return
        if self.preview_thread and self.preview_thread.is_alive():
            self.preview_pending = True
            self.preview_status.config(text="Queued")
            return
        try:
            settings = self.settings()
        except (tk.TclError, ValueError):
            self._set_status("Live preview paused until all settings contain valid numbers.")
            return
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        self.preview_generation += 1
        generation = self.preview_generation
        image_path = self.preview_path
        self.preview_status.config(text="Updating...")
        self.preview_thread = threading.Thread(target=self._preview_worker, args=(generation, image_path, settings), daemon=True)
        self.preview_thread.start()

    def _preview_worker(self, generation, image_path, settings):
        index = self.image_paths.index(image_path) if image_path in self.image_paths else 0
        output_filename = preview_filename_for(index, image_path)
        payload = run_analysis(image_path, PREVIEW_DIR, output_filename, settings)
        payload["Source_Path"] = image_path
        self.event_queue.put(("preview_result", generation, payload))
        self.event_queue.put(("preview_done", generation))

    def apply_preview_payload(self, payload):
        if not payload.get("ok"):
            self.preview_result.config(text=payload.get("error", "Preview failed."))
            self.preview_status.config(text="")
            return
        result = payload["result"]
        output_path = result.get("Output_Path")
        if output_path:
            self.load_preview_image(output_path)
        self.preview_result.config(text=f"Max {result['Max_Diameter_cm']} cm   Min {result['Min_Diameter_cm']} cm")

    def load_preview_image(self, path):
        if not path or not os.path.exists(path):
            return
        try:
            photo = tk.PhotoImage(file=path)
            max_w = max(360, self.preview_label.winfo_width() - 20)
            max_h = max(280, self.preview_label.winfo_height() - 20)
            shrink = max(1, int(max(photo.width() / max_w, photo.height() / max_h)))
            if shrink > 1:
                photo = photo.subsample(shrink, shrink)
            self.preview_photo = photo
            self.preview_label.config(image=self.preview_photo, text="")
        except tk.TclError as exc:
            self.preview_label.config(text=f"Preview unavailable: {exc}", image="")

    def settings(self):
        blur = int(self.blur_var.get())
        if blur % 2 == 0:
            blur += 1
        return {
            "plate_diameter_cm": float(self.plate_diameter_var.get()),
            "growth_threshold": int(float(self.threshold_var.get())),
            "median_blur_size": blur,
            "max_center_deviation_percent": float(self.center_zone_var.get()),
            "morph_close_kernel_size": max(1, int(float(self.close_kernel_var.get()))),
            "clahe_clip_limit": float(self.clahe_var.get()),
        }

    def write_current_csv(self):
        rows = [self.results_by_path[path] for path in self.image_paths if path in self.results_by_path]
        if rows:
            write_csv(os.path.join(self.output_dir_var.get(), "growth_analysis_results.csv"), rows)

    def update_reanalyze_button(self):
        if self.table.selection() and not self.is_busy():
            self.reanalyze_button.state(["!disabled"])
        else:
            self.reanalyze_button.state(["disabled"])

    def open_output_dir(self):
        os.makedirs(self.output_dir_var.get(), exist_ok=True)
        subprocess.run(["open", self.output_dir_var.get()], check=False)

    def is_busy(self):
        batch_busy = self.batch_thread is not None and self.batch_thread.is_alive()
        return batch_busy

    def _set_status(self, text):
        self.status_label.config(text=text)


def find_image_paths(folder):
    paths = []
    for root, _, files in os.walk(folder):
        for file_name in files:
            if file_name.lower().endswith(SUPPORTED_IMAGE_EXTENSIONS):
                paths.append(os.path.join(root, file_name))
    return paths


def run_analysis(image_path, output_dir, output_filename, settings):
    command = [
        ANALYSIS_PYTHON,
        WORKER_PATH,
        image_path,
        "--output-dir",
        output_dir,
        "--output-filename",
        output_filename,
        "--plate-diameter-cm",
        str(settings["plate_diameter_cm"]),
        "--growth-threshold",
        str(settings["growth_threshold"]),
        "--median-blur-size",
        str(settings["median_blur_size"]),
        "--max-center-deviation-percent",
        str(settings["max_center_deviation_percent"]),
        "--morph-close-kernel-size",
        str(settings["morph_close_kernel_size"]),
        "--clahe-clip-limit",
        str(settings["clahe_clip_limit"]),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        return {"ok": False, "error": completed.stderr.strip() or completed.stdout.strip()}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": completed.stderr.strip() or completed.stdout.strip()}


def output_filename_for(index, path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"analyzed_{index + 1:03d}_{stem}.png"


def preview_filename_for(index, path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"preview_{index + 1:03d}_{stem}.png"


def write_csv(path, rows):
    fieldnames = ["Filename", "Source_Path", "Status", "Max_Diameter_cm", "Min_Diameter_cm", "Pixel_to_CM_Ratio", "Output_Path"]
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


if __name__ == "__main__":
    root = tk.Tk()
    app = GrowthAnalyzerGUI(root)
    root.mainloop()
