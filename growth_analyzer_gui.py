#!/usr/local/bin/python3

import csv
import json
import math
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

import count_colonies

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageTk
except ImportError:
    Image = None
    ImageDraw = None
    ImageEnhance = None
    ImageTk = None


APP_TITLE = "Agar Plate Analysis Suite"
SWIM_TITLE = "Swim Diameter Analyzer"
COLONY_TITLE = "Colony Counter"
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKER_PATH = os.path.join(PROJECT_DIR, "analysis_worker.py")
OUTPUT_DIR = os.path.join(PROJECT_DIR, "output")
PREVIEW_DIR = os.path.join(OUTPUT_DIR, "live_preview")
COLONY_OUTPUT_DIR = os.path.join(PROJECT_DIR, "colony_output")
COLONY_PREVIEW_DIR = os.path.join(COLONY_OUTPUT_DIR, "live_preview")
SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")
PREVIEW_DEBOUNCE_MS = 900
STARTUP_LOG_PATH = os.path.join(PROJECT_DIR, "gui_startup.log")

SETTING_HELP = {
    "Plate diameter (cm)": "The real width of your agar plate. This converts pixels into centimeters. If this is wrong, every measurement will be scaled wrong.",
    "Detection sensitivity": "Controls how readily the app accepts faint growth after it compares the colony to that plate's own background. Move left to avoid noise. Move right to capture wider, lighter growth.",
    "Preview contrast": "Changes only how the preview looks on screen. It does not change the measurement algorithm, the saved analysis image, or the CSV results.",
    "Binary threshold": "How bright a pixel must be to count as colony material. Lower values detect fainter colonies but can include more background noise.",
    "Erosion passes": "How much the image is gently shrunk before counting. A little erosion helps split colonies that are touching.",
    "Minimum solidity": "How round and filled-in a colony candidate must be. Higher values reject irregular scratches or artifacts.",
    "Minimum colony area": "Smallest spot, in pixels, that can count as a colony. Raise this to ignore tiny specks.",
    "Maximum colony area": "Largest spot, in pixels, that can count as one colony. Lower this to reject large blobs or plate artifacts.",
}

DEFAULTS = {
    "plate_diameter_cm": 10.0,
    "sensitivity": 50.0,
    "preview_contrast": 1.0,
}

COLONY_DEFAULTS = {
    "binary_threshold": float(count_colonies.BINARY_THRESHOLD),
    "erosion_iterations": float(count_colonies.EROSION_ITERATIONS),
    "min_solidity": float(count_colonies.MIN_SOLIDITY),
    "min_colony_area": float(count_colonies.MIN_COLONY_AREA),
    "max_colony_area": float(count_colonies.MAX_COLONY_AREA),
    "preview_contrast": 1.0,
}


def log_startup(message):
    with open(STARTUP_LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"{message}\n")


class InfoButton(tk.Canvas):
    def __init__(self, parent, text):
        super().__init__(parent, width=22, height=22, highlightthickness=0, bd=0)
        self.tooltip_text = text
        self.tooltip = None
        self.configure(cursor="arrow")
        self.bind("<Enter>", self.show_tooltip)
        self.bind("<Leave>", self.hide_tooltip)
        self._draw(active=False)

    def show_tooltip(self, _event=None):
        self._draw(active=True)
        if self.tooltip or not self.tooltip_text:
            return
        self.tooltip = tk.Toplevel(self)
        self.tooltip.wm_overrideredirect(True)
        self.tooltip.wm_attributes("-topmost", True)
        x = self.winfo_rootx() + 26
        y = self.winfo_rooty() - 6
        self.tooltip.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            self.tooltip,
            text=self.tooltip_text,
            justify="left",
            wraplength=260,
            background="#f9fafb",
            foreground="#111827",
            relief="solid",
            borderwidth=1,
            padx=10,
            pady=7,
            font=("Helvetica", 12),
        )
        label.pack()

    def hide_tooltip(self, _event=None):
        self._draw(active=False)
        if self.tooltip:
            self.tooltip.destroy()
            self.tooltip = None

    def _draw(self, active=False):
        self.delete("all")
        color = "#6b7280" if not active else "#4b5563"
        self.create_oval(2, 2, 20, 20, outline=color, width=2)
        self.create_text(11, 11, text="i", fill=color, font=("Helvetica", 13, "bold"))


class ProgramLauncher:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x560")
        self.root.minsize(760, 480)
        self._load_theme()
        self.show_home()
        self.root.after(150, self.show_window)

    def _load_theme(self):
        try:
            self.root.tk.call("source", os.path.join(PROJECT_DIR, "azure.tcl"))
            self.root.tk.call("set_theme", "light")
        except tk.TclError:
            pass

    def clear_root(self):
        for child in self.root.winfo_children():
            child.destroy()

    def show_window(self):
        self.root.update_idletasks()
        width = min(900, max(760, self.root.winfo_screenwidth() - 160))
        height = min(560, max(480, self.root.winfo_screenheight() - 160))
        x = max(20, (self.root.winfo_screenwidth() - width) // 2)
        y = max(20, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def show_home(self):
        self.clear_root()
        self.root.title(APP_TITLE)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        page = ttk.Frame(self.root, padding=34)
        page.grid(row=0, column=0, sticky="nsew")
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)

        ttk.Label(page, text=APP_TITLE, font=("Helvetica", 24, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(page, text="Choose the analysis tool you want to run.").grid(row=1, column=0, sticky="w", pady=(4, 28))

        cards = ttk.Frame(page)
        cards.grid(row=2, column=0, sticky="nsew")
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

        self._program_card(
            cards,
            0,
            "Swim Diameter Program",
            "Measure growth diameters and area from agar plate scan images.",
            self.launch_swim,
        )
        self._program_card(
            cards,
            1,
            "Colony Counter Program",
            "Count bacterial colonies and export annotated images plus a CSV.",
            self.launch_colony_counter,
        )

    def _program_card(self, parent, column, title, description, command):
        card = ttk.LabelFrame(parent, text=title, padding=18)
        card.grid(row=0, column=column, sticky="nsew", padx=(0, 12) if column == 0 else (12, 0))
        card.columnconfigure(0, weight=1)
        ttk.Label(card, text=description, wraplength=300).grid(row=0, column=0, sticky="nw", pady=(0, 22))
        ttk.Button(card, text="Open", command=command, style="Accent.TButton").grid(row=1, column=0, sticky="ew")

    def launch_swim(self):
        self.clear_root()
        GrowthAnalyzerGUI(self.root)

    def launch_colony_counter(self):
        self.clear_root()
        ColonyCounterGUI(self.root)


class GrowthAnalyzerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(SWIM_TITLE)
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
        self.preview_display_path = None
        self.preview_photo = None
        self.preview_image_item = None
        self.preview_image_box = None
        self.preview_source_size = None
        self.current_preview_result = None
        self.manual_edit_enabled = False
        self.manual_drag_start = None
        self.manual_drag_mode = None
        self.manual_ellipse_item = None
        self.manual_handle_items = []
        self.manual_edit_rect_image = None
        self.manual_undo_by_path = {}

        self.output_dir_var = tk.StringVar(value=OUTPUT_DIR)
        self.plate_diameter_var = tk.DoubleVar(value=DEFAULTS["plate_diameter_cm"])
        self.sensitivity_var = tk.DoubleVar(value=DEFAULTS["sensitivity"])
        self.preview_contrast_var = tk.DoubleVar(value=DEFAULTS["preview_contrast"])
        self.preview_contrast_rounding = False

        self._load_theme()
        self._build_ui()
        self._bind_preview_traces()
        self._set_status("Choose a folder or images. Select one row to tune the live preview.")
        self.root.after(150, self.show_window)
        self.root.after(100, self._drain_event_queue)

    def _load_theme(self):
        try:
            self.root.tk.call("source", os.path.join(PROJECT_DIR, "azure.tcl"))
            self.root.tk.call("set_theme", "light")
        except tk.TclError:
            pass

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_paned = tk.PanedWindow(
            self.root,
            orient=tk.HORIZONTAL,
            sashwidth=6,
            sashrelief="flat",
            showhandle=False,
            bd=0,
            bg="#eef2f7",
            opaqueresize=True,
        )
        main_paned.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(main_paned, padding=(18, 16), width=340)
        controls.grid_propagate(False)
        controls.columnconfigure(0, weight=1)

        workspace_shell = ttk.Frame(main_paned, padding=(0, 16, 18, 16))
        workspace_shell.columnconfigure(0, weight=1)
        workspace_shell.rowconfigure(0, weight=1)

        workspace = tk.PanedWindow(
            workspace_shell,
            orient=tk.VERTICAL,
            sashwidth=5,
            sashrelief="flat",
            showhandle=False,
            bd=0,
            bg="#eef2f7",
            opaqueresize=True,
        )
        workspace.grid(row=0, column=0, sticky="nsew")

        preview_panel = ttk.Frame(workspace)
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(0, weight=1)

        table_panel = ttk.Frame(workspace)
        table_panel.columnconfigure(0, weight=1)
        table_panel.rowconfigure(0, weight=1)

        main_paned.add(controls, minsize=280, width=340)
        main_paned.add(workspace_shell, minsize=560)
        workspace.add(preview_panel, minsize=220, height=450)
        workspace.add(table_panel, minsize=72)

        self._build_controls(controls)
        self._build_preview(preview_panel)
        self._build_table(table_panel)

    def show_window(self):
        self.root.update_idletasks()
        width = min(1240, max(980, self.root.winfo_screenwidth() - 120))
        height = min(780, max(640, self.root.winfo_screenheight() - 120))
        x = max(20, (self.root.winfo_screenwidth() - width) // 2)
        y = max(20, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", True)
        self.root.after(800, lambda: self.root.attributes("-topmost", False))

    def _build_controls(self, parent):
        ttk.Label(parent, text=SWIM_TITLE, font=("Helvetica", 18, "bold")).grid(row=0, column=0, sticky="w")
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
        ttk.Button(output, text="Show Results Folder", command=self.open_output_dir).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        settings = ttk.LabelFrame(parent, text="Auto Analysis Settings", padding=12)
        settings.grid(row=5, column=0, sticky="ew")
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(1, weight=0)
        self._spin(settings, 0, "Plate diameter (cm)", self.plate_diameter_var, 1.0, 30.0, 0.1)
        self._sensitivity(settings, 2)
        self._preview_contrast(settings, 5)

        self.run_button = ttk.Button(parent, text="Run Batch Analysis", command=self.start_batch_analysis, style="Accent.TButton")
        self.run_button.grid(row=6, column=0, sticky="ew", pady=(18, 8), ipady=4)
        self.manual_edit_button = ttk.Button(parent, text="Adjust Shape Manually", command=self.toggle_manual_edit, state="disabled")
        self.manual_edit_button.grid(row=7, column=0, sticky="ew", pady=(0, 8))
        self.undo_manual_button = ttk.Button(parent, text="Undo Manual Changes", command=self.undo_manual_changes, state="disabled")
        self.undo_manual_button.grid(row=8, column=0, sticky="ew", pady=(0, 8))

        self.progress = ttk.Progressbar(parent, mode="determinate")
        self.progress.grid(row=9, column=0, sticky="ew", pady=(16, 6))
        self.status_label = ttk.Label(parent, text="", wraplength=300)
        self.status_label.grid(row=10, column=0, sticky="ew")

    def _spin(self, parent, row, label, variable, from_, to, increment):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(0, 4))
        self._info_button(parent, row, label)
        ttk.Spinbox(parent, textvariable=variable, from_=from_, to=to, increment=increment).grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

    def _sensitivity(self, parent, row):
        self.sensitivity_label_var = tk.StringVar()

        def update_label(*_):
            value = self.sensitivity_var.get()
            if value < 20:
                zone = "Very conservative"
            elif value < 40:
                zone = "Conservative"
            elif value > 80:
                zone = "Very sensitive"
            elif value > 60:
                zone = "Sensitive"
            else:
                zone = "Balanced"
            self.sensitivity_label_var.set(f"Detection sensitivity: {zone}")

        self.sensitivity_var.trace_add("write", update_label)
        update_label()
        ttk.Label(parent, textvariable=self.sensitivity_label_var).grid(row=row, column=0, sticky="w", pady=(0, 4))
        self._info_button(parent, row, "Detection sensitivity")
        sensitivity = ttk.Scale(parent, variable=self.sensitivity_var, from_=0, to=100)
        self.bind_scale_click_to_value(sensitivity, self.sensitivity_var, 0, 100)
        sensitivity.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 2))

        axis = ttk.Frame(parent)
        axis.grid(row=row + 2, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        axis.columnconfigure(0, weight=1)
        axis.columnconfigure(1, weight=1)
        axis.columnconfigure(2, weight=1)
        ttk.Label(axis, text="Very conservative").grid(row=0, column=0, sticky="w")
        ttk.Label(axis, text="Balanced").grid(row=0, column=1)
        ttk.Label(axis, text="Very sensitive").grid(row=0, column=2, sticky="e")

    def _preview_contrast(self, parent, row):
        self.preview_contrast_label_var = tk.StringVar()

        def update_label(*_):
            self.preview_contrast_label_var.set(f"Preview contrast: {self.preview_contrast_var.get():.1f}x")

        self.preview_contrast_var.trace_add("write", update_label)
        update_label()
        ttk.Label(parent, textvariable=self.preview_contrast_label_var).grid(row=row, column=0, sticky="w", pady=(0, 4))
        self._info_button(parent, row, "Preview contrast")
        contrast_row = ttk.Frame(parent)
        contrast_row.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        contrast_row.columnconfigure(0, weight=1)
        contrast = ttk.Scale(contrast_row, variable=self.preview_contrast_var, from_=0.4, to=3.0)
        self.bind_scale_click_to_value(contrast, self.preview_contrast_var, 0.4, 3.0, precision=1)
        contrast.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Spinbox(contrast_row, textvariable=self.preview_contrast_var, from_=0.4, to=3.0, increment=0.1, width=6).grid(row=0, column=1)

        axis = ttk.Frame(parent)
        axis.grid(row=row + 2, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        axis.columnconfigure(0, weight=1)
        axis.columnconfigure(1, weight=1)
        axis.columnconfigure(2, weight=1)
        ttk.Label(axis, text="Softer").grid(row=0, column=0, sticky="w")
        ttk.Label(axis, text="Original").grid(row=0, column=1)
        ttk.Label(axis, text="Higher contrast").grid(row=0, column=2, sticky="e")

    def bind_scale_click_to_value(self, scale, variable, from_, to, precision=None):
        def jump_to_click(event):
            width = max(1, scale.winfo_width())
            fraction = min(1.0, max(0.0, event.x / width))
            value = from_ + (to - from_) * fraction
            if precision is not None:
                value = round(value, precision)
            variable.set(value)

        scale.bind("<Button-1>", jump_to_click, add="+")

    def _info_button(self, parent, row, label):
        InfoButton(parent, SETTING_HELP.get(label, "This setting changes how the plate image is processed.")).grid(row=row, column=1, sticky="e", padx=(8, 0), pady=(0, 4))

    def _build_preview(self, parent):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        self.preview_title = ttk.Label(header, text="Live Preview", font=("Helvetica", 13, "bold"))
        self.preview_title.grid(row=0, column=0, sticky="w")
        self.preview_status = ttk.Label(header, text="")
        self.preview_status.grid(row=0, column=1, sticky="e")

        self.preview_canvas = tk.Canvas(frame, highlightthickness=0, background="#f4f6f8")
        self.preview_canvas.grid(row=1, column=0, sticky="nsew")
        self.preview_canvas.create_text(20, 20, text="Select a row to tune this image.", anchor="nw", fill="#5f6b7a", tags=("placeholder",))
        self.preview_canvas.bind("<ButtonPress-1>", self.on_preview_press)
        self.preview_canvas.bind("<B1-Motion>", self.on_preview_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self.on_preview_release)
        self.preview_canvas.bind("<Configure>", lambda _event: self.refresh_preview_display())
        self.preview_result = ttk.Label(frame, text="", anchor="center")
        self.preview_result.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_table(self, parent):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=0, sticky="nsew")
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
        self.preview_display_path = None
        self.preview_photo = None
        self.preview_generation += 1
        for item in self.table.get_children():
            self.table.delete(item)
        self.preview_title.config(text="Live Preview")
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(20, 20, text="Select a row to tune this image.", anchor="nw", fill="#5f6b7a", tags=("placeholder",))
        self.preview_result.config(text="")
        self.preview_status.config(text="")
        self.progress["value"] = 0
        self.manual_edit_button.state(["disabled"])
        self.undo_manual_button.state(["disabled"])
        self.manual_edit_enabled = False
        self.manual_drag_start = None
        self.manual_drag_mode = None
        self.manual_edit_rect_image = None
        self.manual_edit_button.config(text="Adjust Shape Manually")
        self.preview_canvas.config(cursor="")
        self.current_preview_result = None
        self.manual_undo_by_path = {}
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
        self.manual_edit_button.state(["disabled"])
        self.undo_manual_button.state(["disabled"])
        manual_locked_paths = {
            path
            for path, result in self.results_by_path.items()
            if self.is_manual_result(result)
        }
        self.batch_thread = threading.Thread(target=self._batch_worker, args=(settings, manual_locked_paths), daemon=True)
        self.batch_thread.start()

    def _batch_worker(self, settings, manual_locked_paths):
        for index, image_path in enumerate(self.image_paths):
            if image_path in manual_locked_paths:
                self.event_queue.put(("manual_kept", index, image_path))
                self.event_queue.put(("progress", index + 1))
                continue
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
            self.manual_undo_by_path.pop(result["Source_Path"], None)
            self.results_by_path[result["Source_Path"]] = result
            self.update_row(index, result["Status"], result["Max_Diameter_cm"], result["Min_Diameter_cm"], result["Pixel_to_CM_Ratio"])
            if result["Source_Path"] == self.preview_path:
                self.apply_preview_payload({"ok": True, "result": result})
            self.write_current_csv()
        elif kind == "manual_kept":
            _, index, image_path = event
            result = self.results_by_path.get(image_path)
            if result:
                self.update_row(index, "Manual Kept", result.get("Max_Diameter_cm", ""), result.get("Min_Diameter_cm", ""), result.get("Pixel_to_CM_Ratio", ""))
                if image_path == self.preview_path:
                    self.current_preview_result = result
                    self.preview_result.config(text=self.result_summary_text(result, prefix="Manual: "))
        elif kind == "progress":
            self.progress["value"] = event[1]
            self._set_status(f"Analyzed {event[1]} of {len(self.image_paths)} image(s).")
        elif kind == "batch_done":
            self.batch_thread = None
            self.run_button.state(["!disabled"])
            self.update_action_buttons()
            self._set_status(f"Finished: {len(self.results_by_path)} measured result(s). Select a row to inspect or manually adjust it.")
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
            self.update_action_buttons()
            return
        self.set_preview_path(self.row_paths.get(selection[0]))
        self.update_action_buttons()

    def set_preview_path(self, path):
        if not path:
            return
        self.manual_edit_enabled = False
        self.manual_drag_start = None
        self.manual_drag_mode = None
        self.manual_edit_rect_image = None
        self.manual_edit_button.config(text="Adjust Shape Manually")
        self.preview_canvas.config(cursor="")
        self.preview_canvas.delete("manual_overlay")
        self.preview_path = path
        self.preview_title.config(text=os.path.basename(path))
        self.preview_status.config(text="")
        result = self.results_by_path.get(path)
        if result:
            self.apply_preview_payload({"ok": True, "result": result})
        else:
            self.current_preview_result = None
            self.manual_edit_button.state(["disabled"])
            self.update_undo_button()
            self.preview_result.config(text="Live preview updates after settings settle.")
            self.schedule_live_preview(delay=150)

    def _bind_preview_traces(self):
        for variable in (
            self.plate_diameter_var,
            self.sensitivity_var,
        ):
            variable.trace_add("write", lambda *_: self.schedule_live_preview())
        self.preview_contrast_var.trace_add("write", self.on_preview_contrast_changed)

    def on_preview_contrast_changed(self, *_):
        if self.preview_contrast_rounding:
            return
        try:
            current_value = float(self.preview_contrast_var.get())
        except (tk.TclError, ValueError):
            return
        rounded_value = round(current_value, 1)
        if abs(current_value - rounded_value) > 0.00001:
            self.preview_contrast_rounding = True
            self.preview_contrast_var.set(rounded_value)
            self.preview_contrast_rounding = False
        self.refresh_preview_display()

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
            self.current_preview_result = None
            self.manual_edit_button.state(["disabled"])
            self.update_undo_button()
            return
        result = payload["result"]
        self.current_preview_result = result
        output_path = result.get("Output_Path")
        if output_path:
            self.load_preview_image(output_path)
        self.preview_result.config(text=self.result_summary_text(result))
        self.manual_edit_button.state(["!disabled"])
        self.update_undo_button()

    def load_preview_image(self, path):
        if not path or not os.path.exists(path):
            return
        try:
            self.preview_display_path = path
            self.refresh_preview_display()
        except tk.TclError as exc:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(20, 20, text=f"Preview unavailable: {exc}", anchor="nw", fill="#5f6b7a")

    def refresh_preview_display(self):
        path = self.preview_display_path
        if not path or not os.path.exists(path):
            return
        try:
            max_w = max(360, self.preview_canvas.winfo_width() - 20)
            max_h = max(280, self.preview_canvas.winfo_height() - 20)
            if Image is not None and ImageTk is not None and ImageEnhance is not None:
                image = Image.open(path).convert("RGB")
                self.preview_source_size = image.size
                contrast = float(self.preview_contrast_var.get())
                image = ImageEnhance.Contrast(image).enhance(contrast)
                image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                self.preview_photo = ImageTk.PhotoImage(image)
            else:
                photo = tk.PhotoImage(file=path)
                self.preview_source_size = (photo.width(), photo.height())
                shrink = max(1, int(max(photo.width() / max_w, photo.height() / max_h)))
                if shrink > 1:
                    photo = photo.subsample(shrink, shrink)
                self.preview_photo = photo
            self.preview_canvas.delete("all")
            canvas_w = max(1, self.preview_canvas.winfo_width())
            canvas_h = max(1, self.preview_canvas.winfo_height())
            image_w = self.preview_photo.width()
            image_h = self.preview_photo.height()
            x = max(0, (canvas_w - image_w) // 2)
            y = max(0, (canvas_h - image_h) // 2)
            self.preview_image_box = (x, y, image_w, image_h)
            self.preview_image_item = self.preview_canvas.create_image(x, y, image=self.preview_photo, anchor="nw")
            if self.manual_edit_enabled:
                self.draw_manual_overlay()
        except (tk.TclError, OSError, ValueError) as exc:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(20, 20, text=f"Preview unavailable: {exc}", anchor="nw", fill="#5f6b7a")

    def settings(self):
        return {
            "plate_diameter_cm": float(self.plate_diameter_var.get()),
            "sensitivity": round(float(self.sensitivity_var.get()), 1),
        }

    def toggle_manual_edit(self):
        if not self.current_preview_result or not self.preview_path:
            messagebox.showinfo("No Preview Result", "Run or select a measured preview before adjusting the shape manually.")
            return
        self.manual_edit_enabled = not self.manual_edit_enabled
        if self.manual_edit_enabled:
            self.manual_edit_button.config(text="Apply Shape Adjustment")
            self.preview_canvas.config(cursor="crosshair")
            self.initialize_manual_overlay()
            self._set_status("Manual shape mode: drag the ellipse edge or handles, then click Apply Shape Adjustment.")
        else:
            if self.manual_edit_rect_image:
                self.apply_manual_ellipse(*self.manual_edit_rect_image)

    def on_preview_press(self, event):
        if not self.manual_edit_enabled or not self.point_in_preview_image(event.x, event.y):
            return
        self.manual_drag_mode = self.get_manual_drag_mode(event.x, event.y)
        if not self.manual_drag_mode:
            return
        self.manual_drag_start = (event.x, event.y, self.manual_edit_rect_image)

    def on_preview_drag(self, event):
        if not self.manual_edit_enabled or not self.manual_drag_start or not self.manual_edit_rect_image:
            return
        start_x, start_y, start_rect = self.manual_drag_start
        x, y = self.clamp_to_preview_image(event.x, event.y)
        start_img_x, start_img_y = self.canvas_point_to_image_point(start_x, start_y)
        img_x, img_y = self.canvas_point_to_image_point(x, y)
        dx = img_x - start_img_x
        dy = img_y - start_img_y
        left, top, right, bottom = start_rect
        mode = self.manual_drag_mode or "move"
        if "left" in mode:
            left += dx
        if "right" in mode:
            right += dx
        if "top" in mode:
            top += dy
        if "bottom" in mode:
            bottom += dy
        if mode == "move":
            left += dx
            right += dx
            top += dy
            bottom += dy
        self.manual_edit_rect_image = self.normalize_image_rect(left, top, right, bottom)
        self.draw_manual_overlay()

    def on_preview_release(self, event):
        if not self.manual_edit_enabled or not self.manual_drag_start:
            return
        self.manual_drag_start = None
        self.manual_drag_mode = None
        self._set_status("Shape adjusted. Click Apply Shape Adjustment to save, or Undo Manual Changes to restore the previous measurement.")

    def point_in_preview_image(self, x, y):
        if not self.preview_image_box:
            return False
        image_x, image_y, image_w, image_h = self.preview_image_box
        return image_x <= x <= image_x + image_w and image_y <= y <= image_y + image_h

    def clamp_to_preview_image(self, x, y):
        if not self.preview_image_box:
            return x, y
        image_x, image_y, image_w, image_h = self.preview_image_box
        return (
            min(max(x, image_x), image_x + image_w),
            min(max(y, image_y), image_y + image_h),
        )

    def canvas_point_to_image_point(self, x, y):
        if not self.preview_image_box or not self.preview_source_size:
            return x, y
        image_x, image_y, image_w, image_h = self.preview_image_box
        source_w, source_h = self.preview_source_size
        if image_w <= 0 or image_h <= 0:
            return x, y
        return (
            (x - image_x) * source_w / image_w,
            (y - image_y) * source_h / image_h,
        )

    def image_rect_to_canvas_rect(self, rect):
        if not self.preview_image_box or not self.preview_source_size:
            return rect
        left, top, right, bottom = rect
        image_x, image_y, image_w, image_h = self.preview_image_box
        source_w, source_h = self.preview_source_size
        if source_w <= 0 or source_h <= 0:
            return rect
        return (
            image_x + left * image_w / source_w,
            image_y + top * image_h / source_h,
            image_x + right * image_w / source_w,
            image_y + bottom * image_h / source_h,
        )

    def normalize_image_rect(self, left, top, right, bottom):
        if not self.preview_source_size:
            return (left, top, right, bottom)
        source_w, source_h = self.preview_source_size
        min_size = max(10.0, min(source_w, source_h) * 0.02)
        left, right = sorted((float(left), float(right)))
        top, bottom = sorted((float(top), float(bottom)))
        left = min(max(left, 0.0), float(source_w))
        right = min(max(right, 0.0), float(source_w))
        top = min(max(top, 0.0), float(source_h))
        bottom = min(max(bottom, 0.0), float(source_h))

        if right - left < min_size:
            center_x = (left + right) / 2
            left = center_x - min_size / 2
            right = center_x + min_size / 2
        if bottom - top < min_size:
            center_y = (top + bottom) / 2
            top = center_y - min_size / 2
            bottom = center_y + min_size / 2

        if left < 0:
            right -= left
            left = 0.0
        if right > source_w:
            left -= right - source_w
            right = float(source_w)
        if top < 0:
            bottom -= top
            top = 0.0
        if bottom > source_h:
            top -= bottom - source_h
            bottom = float(source_h)
        return (
            min(max(left, 0.0), float(source_w)),
            min(max(top, 0.0), float(source_h)),
            min(max(right, 0.0), float(source_w)),
            min(max(bottom, 0.0), float(source_h)),
        )

    def initialize_manual_overlay(self):
        if not self.preview_source_size:
            return
        bbox = self.current_preview_result.get("Ellipse_BBox_px") if self.current_preview_result else None
        if isinstance(bbox, str):
            try:
                bbox = json.loads(bbox)
            except json.JSONDecodeError:
                bbox = None
        if bbox and len(bbox) == 4:
            left, top, right, bottom = [float(value) for value in bbox]
        else:
            source_w, source_h = self.preview_source_size
            left, right = source_w * 0.25, source_w * 0.75
            top, bottom = source_h * 0.25, source_h * 0.75
        self.manual_edit_rect_image = self.normalize_image_rect(left, top, right, bottom)
        self.draw_manual_overlay()

    def draw_manual_overlay(self):
        self.preview_canvas.delete("manual_overlay")
        self.manual_ellipse_item = None
        self.manual_handle_items = []
        if not self.manual_edit_enabled or not self.manual_edit_rect_image or not self.preview_image_box:
            return
        left, top, right, bottom = self.image_rect_to_canvas_rect(self.manual_edit_rect_image)
        self.manual_ellipse_item = self.preview_canvas.create_oval(
            left,
            top,
            right,
            bottom,
            outline="#dc2626",
            width=3,
            tags=("manual_overlay",),
        )
        handle_points = (
            (left, top),
            ((left + right) / 2, top),
            (right, top),
            (right, (top + bottom) / 2),
            (right, bottom),
            ((left + right) / 2, bottom),
            (left, bottom),
            (left, (top + bottom) / 2),
        )
        for handle_x, handle_y in handle_points:
            size = 5
            item = self.preview_canvas.create_rectangle(
                handle_x - size,
                handle_y - size,
                handle_x + size,
                handle_y + size,
                fill="#ffffff",
                outline="#dc2626",
                width=2,
                tags=("manual_overlay",),
            )
            self.manual_handle_items.append(item)

    def get_manual_drag_mode(self, x, y):
        if not self.manual_edit_rect_image:
            return None
        left, top, right, bottom = self.image_rect_to_canvas_rect(self.manual_edit_rect_image)
        threshold = 12
        near_left = abs(x - left) <= threshold
        near_right = abs(x - right) <= threshold
        near_top = abs(y - top) <= threshold
        near_bottom = abs(y - bottom) <= threshold
        inside = left <= x <= right and top <= y <= bottom
        if near_left and near_top:
            return "left-top"
        if near_right and near_top:
            return "right-top"
        if near_right and near_bottom:
            return "right-bottom"
        if near_left and near_bottom:
            return "left-bottom"
        if near_left and inside:
            return "left"
        if near_right and inside:
            return "right"
        if near_top and inside:
            return "top"
        if near_bottom and inside:
            return "bottom"
        if inside:
            return "move"
        return None

    def apply_manual_ellipse(self, x0, y0, x1, y1):
        if not self.current_preview_result or not self.preview_path or not self.preview_image_box or not self.preview_source_size:
            return
        ratio = float(self.current_preview_result.get("Pixel_to_CM_Ratio", 0))
        if ratio <= 0:
            messagebox.showerror("Missing Scale", "This image does not have a valid pixel-to-centimeter scale yet.")
            return
        left, top, right, bottom = self.normalize_image_rect(x0, y0, x1, y1)
        width_px = abs(right - left)
        height_px = abs(bottom - top)
        max_cm = round(max(width_px, height_px) / ratio, 2)
        min_cm = round(min(width_px, height_px) / ratio, 2)
        area_cm2 = round(math.pi * (max_cm / 2) * (min_cm / 2), 2)
        if self.preview_path not in self.manual_undo_by_path:
            previous = dict(self.current_preview_result)
            previous["Source_Path"] = self.preview_path
            self.manual_undo_by_path[self.preview_path] = previous
        output_path = self.save_manual_annotation(left, top, right, bottom, max_cm, min_cm)
        result = dict(self.current_preview_result)
        result.update({
            "Status": "Manual Edit",
            "Method": "Manual Ellipse",
            "Max_Diameter_cm": max_cm,
            "Min_Diameter_cm": min_cm,
            "Area_cm2": area_cm2,
            "Output_Path": output_path or result.get("Output_Path", ""),
            "Source_Path": self.preview_path,
            "Ellipse_BBox_px": [left, top, right, bottom],
        })
        self.current_preview_result = result
        self.results_by_path[self.preview_path] = result
        index = self.image_paths.index(self.preview_path) if self.preview_path in self.image_paths else 0
        self.update_row(index, "Manual Edit", max_cm, min_cm, result.get("Pixel_to_CM_Ratio", ""))
        self.write_current_csv()
        self.manual_edit_enabled = False
        self.manual_drag_start = None
        self.manual_drag_mode = None
        self.manual_edit_button.config(text="Adjust Shape Manually")
        self.preview_canvas.config(cursor="")
        if output_path:
            self.load_preview_image(output_path)
        else:
            self.preview_canvas.delete("manual_overlay")
        self.preview_result.config(text=self.result_summary_text(result, prefix="Manual: "))
        self.update_undo_button()
        self._set_status("Manual measurement saved for the selected image.")

    def save_manual_annotation(self, left, top, right, bottom, max_cm, min_cm):
        if Image is None or ImageDraw is None:
            return ""
        try:
            crop_box = self.current_preview_result.get("Crop_Box_px", [])
            if isinstance(crop_box, str):
                try:
                    crop_box = json.loads(crop_box)
                except json.JSONDecodeError:
                    crop_box = []
            if len(crop_box) == 4 and self.preview_path and os.path.exists(self.preview_path):
                image = Image.open(self.preview_path).convert("RGB")
                image = image.crop(tuple(int(value) for value in crop_box))
            else:
                base_path = self.preview_display_path or self.current_preview_result.get("Output_Path")
                if not base_path or not os.path.exists(base_path):
                    return ""
                image = Image.open(base_path).convert("RGB")
            draw = ImageDraw.Draw(image)
            manual_color = (220, 38, 38)
            draw.ellipse((left, top, right, bottom), outline=manual_color, width=5)
            center_y = (top + bottom) / 2
            center_x = (left + right) / 2
            draw.line((left, center_y, right, center_y), fill=manual_color, width=3)
            draw.line((center_x, top, center_x, bottom), fill=manual_color, width=3)
            draw.text((max(10, left), max(10, top - 36)), f"Manual Max: {max_cm:.2f} cm  Min: {min_cm:.2f} cm", fill=(255, 255, 255))
            index = self.image_paths.index(self.preview_path) if self.preview_path in self.image_paths else 0
            output_path = os.path.join(self.output_dir_var.get(), manual_output_filename_for(index, self.preview_path))
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            image.save(output_path)
            return output_path
        except (OSError, ValueError):
            return ""

    def update_undo_button(self):
        if self.preview_path and self.preview_path in self.manual_undo_by_path and not self.is_busy():
            self.undo_manual_button.state(["!disabled"])
        else:
            self.undo_manual_button.state(["disabled"])

    def undo_manual_changes(self):
        if not self.preview_path or self.preview_path not in self.manual_undo_by_path:
            return
        result = self.manual_undo_by_path.pop(self.preview_path)
        result["Source_Path"] = self.preview_path
        self.current_preview_result = result
        self.results_by_path[self.preview_path] = result
        index = self.image_paths.index(self.preview_path) if self.preview_path in self.image_paths else 0
        self.update_row(
            index,
            result.get("Status", "Success"),
            result.get("Max_Diameter_cm", ""),
            result.get("Min_Diameter_cm", ""),
            result.get("Pixel_to_CM_Ratio", ""),
        )
        self.write_current_csv()
        self.manual_edit_enabled = False
        self.manual_drag_start = None
        self.manual_drag_mode = None
        self.manual_edit_rect_image = None
        self.manual_edit_button.config(text="Adjust Shape Manually")
        self.preview_canvas.config(cursor="")
        output_path = result.get("Output_Path")
        if output_path:
            self.load_preview_image(output_path)
        self.preview_result.config(text=self.result_summary_text(result))
        self.update_undo_button()
        self._set_status("Manual change undone for the selected image.")

    def is_manual_result(self, result):
        return result and (result.get("Method") == "Manual Ellipse" or result.get("Status") == "Manual Edit")

    def result_summary_text(self, result, prefix=""):
        max_cm = result.get("Max_Diameter_cm", "")
        min_cm = result.get("Min_Diameter_cm", "")
        area_cm2 = result.get("Area_cm2", "")
        if area_cm2 == "":
            return f"{prefix}Max {max_cm} cm   Min {min_cm} cm"
        return f"{prefix}Max {max_cm} cm   Min {min_cm} cm   Area {area_cm2} cm^2"

    def write_current_csv(self):
        rows = [self.results_by_path[path] for path in self.image_paths if path in self.results_by_path]
        if rows:
            write_csv(os.path.join(self.output_dir_var.get(), "growth_analysis_results.csv"), rows)

    def update_action_buttons(self):
        if self.current_preview_result and not self.is_busy():
            self.manual_edit_button.state(["!disabled"])
        else:
            self.manual_edit_button.state(["disabled"])
        self.update_undo_button()

    def open_output_dir(self):
        os.makedirs(self.output_dir_var.get(), exist_ok=True)
        subprocess.run(["open", self.output_dir_var.get()], check=False)

    def is_busy(self):
        batch_busy = self.batch_thread is not None and self.batch_thread.is_alive()
        return batch_busy

    def _set_status(self, text):
        self.status_label.config(text=text)


class ColonyCounterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(COLONY_TITLE)
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
        self.preview_display_path = None
        self.preview_photo = None

        self.output_dir_var = tk.StringVar(value=COLONY_OUTPUT_DIR)
        self.binary_threshold_var = tk.DoubleVar(value=COLONY_DEFAULTS["binary_threshold"])
        self.erosion_iterations_var = tk.DoubleVar(value=COLONY_DEFAULTS["erosion_iterations"])
        self.min_solidity_var = tk.DoubleVar(value=COLONY_DEFAULTS["min_solidity"])
        self.min_colony_area_var = tk.DoubleVar(value=COLONY_DEFAULTS["min_colony_area"])
        self.max_colony_area_var = tk.DoubleVar(value=COLONY_DEFAULTS["max_colony_area"])
        self.preview_contrast_var = tk.DoubleVar(value=COLONY_DEFAULTS["preview_contrast"])
        self.preview_contrast_rounding = False

        self._load_theme()
        self._build_ui()
        self._bind_preview_traces()
        self._set_status("Choose a folder or images. Select one row to tune the live preview.")
        self.root.after(150, self.show_window)
        self.root.after(100, self._drain_event_queue)

    def _load_theme(self):
        try:
            self.root.tk.call("source", os.path.join(PROJECT_DIR, "azure.tcl"))
            self.root.tk.call("set_theme", "light")
        except tk.TclError:
            pass

    def _build_ui(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashwidth=6, sashrelief="flat", showhandle=False, bd=0, bg="#eef2f7", opaqueresize=True)
        main_paned.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(main_paned, padding=(18, 16), width=340)
        controls.grid_propagate(False)
        controls.columnconfigure(0, weight=1)

        workspace_shell = ttk.Frame(main_paned, padding=(0, 16, 18, 16))
        workspace_shell.columnconfigure(0, weight=1)
        workspace_shell.rowconfigure(0, weight=1)

        workspace = tk.PanedWindow(workspace_shell, orient=tk.VERTICAL, sashwidth=5, sashrelief="flat", showhandle=False, bd=0, bg="#eef2f7", opaqueresize=True)
        workspace.grid(row=0, column=0, sticky="nsew")

        preview_panel = ttk.Frame(workspace)
        preview_panel.columnconfigure(0, weight=1)
        preview_panel.rowconfigure(0, weight=1)
        table_panel = ttk.Frame(workspace)
        table_panel.columnconfigure(0, weight=1)
        table_panel.rowconfigure(0, weight=1)

        main_paned.add(controls, minsize=280, width=340)
        main_paned.add(workspace_shell, minsize=560)
        workspace.add(preview_panel, minsize=220, height=450)
        workspace.add(table_panel, minsize=72)

        self._build_controls(controls)
        self._build_preview(preview_panel)
        self._build_table(table_panel)

    def show_window(self):
        self.root.update_idletasks()
        width = min(1240, max(980, self.root.winfo_screenwidth() - 120))
        height = min(780, max(640, self.root.winfo_screenheight() - 120))
        x = max(20, (self.root.winfo_screenwidth() - width) // 2)
        y = max(20, (self.root.winfo_screenheight() - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _build_controls(self, parent):
        ttk.Label(parent, text=COLONY_TITLE, font=("Helvetica", 18, "bold")).grid(row=0, column=0, sticky="w")
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
        ttk.Button(output, text="Show Results Folder", command=self.open_output_dir).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        settings = ttk.LabelFrame(parent, text="Colony Detection Settings", padding=12)
        settings.grid(row=5, column=0, sticky="ew")
        settings.columnconfigure(0, weight=1)
        settings.columnconfigure(1, weight=0)
        self._spin(settings, 0, "Binary threshold", self.binary_threshold_var, 1, 255, 1)
        self._spin(settings, 2, "Erosion passes", self.erosion_iterations_var, 0, 4, 1)
        self._spin(settings, 4, "Minimum solidity", self.min_solidity_var, 0.1, 1.0, 0.01)
        self._spin(settings, 6, "Minimum colony area", self.min_colony_area_var, 1, 2000, 1)
        self._spin(settings, 8, "Maximum colony area", self.max_colony_area_var, 10, 20000, 10)
        self._preview_contrast(settings, 10)

        self.run_button = ttk.Button(parent, text="Run Batch Count", command=self.start_batch_analysis, style="Accent.TButton")
        self.run_button.grid(row=6, column=0, sticky="ew", pady=(18, 8), ipady=4)
        self.progress = ttk.Progressbar(parent, mode="determinate")
        self.progress.grid(row=7, column=0, sticky="ew", pady=(16, 6))
        self.status_label = ttk.Label(parent, text="", wraplength=300)
        self.status_label.grid(row=8, column=0, sticky="ew")

    def _spin(self, parent, row, label, variable, from_, to, increment):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=(0, 4))
        InfoButton(parent, SETTING_HELP.get(label, "This setting changes how colony detection is processed.")).grid(row=row, column=1, sticky="e", padx=(8, 0), pady=(0, 4))
        ttk.Spinbox(parent, textvariable=variable, from_=from_, to=to, increment=increment).grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 10))

    def _preview_contrast(self, parent, row):
        self.preview_contrast_label_var = tk.StringVar()

        def update_label(*_):
            self.preview_contrast_label_var.set(f"Preview contrast: {self.preview_contrast_var.get():.1f}x")

        self.preview_contrast_var.trace_add("write", update_label)
        update_label()
        ttk.Label(parent, textvariable=self.preview_contrast_label_var).grid(row=row, column=0, sticky="w", pady=(0, 4))
        InfoButton(parent, SETTING_HELP["Preview contrast"]).grid(row=row, column=1, sticky="e", padx=(8, 0), pady=(0, 4))
        contrast_row = ttk.Frame(parent)
        contrast_row.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        contrast_row.columnconfigure(0, weight=1)
        contrast = ttk.Scale(contrast_row, variable=self.preview_contrast_var, from_=0.4, to=3.0)
        self.bind_scale_click_to_value(contrast, self.preview_contrast_var, 0.4, 3.0, precision=1)
        contrast.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Spinbox(contrast_row, textvariable=self.preview_contrast_var, from_=0.4, to=3.0, increment=0.1, width=6).grid(row=0, column=1)

    def bind_scale_click_to_value(self, scale, variable, from_, to, precision=None):
        def jump_to_click(event):
            width = max(1, scale.winfo_width())
            fraction = min(1.0, max(0.0, event.x / width))
            value = from_ + (to - from_) * fraction
            if precision is not None:
                value = round(value, precision)
            variable.set(value)

        scale.bind("<Button-1>", jump_to_click, add="+")

    def _build_preview(self, parent):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        header.columnconfigure(0, weight=1)
        self.preview_title = ttk.Label(header, text="Live Preview", font=("Helvetica", 13, "bold"))
        self.preview_title.grid(row=0, column=0, sticky="w")
        self.preview_status = ttk.Label(header, text="")
        self.preview_status.grid(row=0, column=1, sticky="e")

        self.preview_canvas = tk.Canvas(frame, highlightthickness=0, background="#f4f6f8")
        self.preview_canvas.grid(row=1, column=0, sticky="nsew")
        self.preview_canvas.create_text(20, 20, text="Select a row to tune this image.", anchor="nw", fill="#5f6b7a")
        self.preview_canvas.bind("<Configure>", lambda _event: self.refresh_preview_display())
        self.preview_result = ttk.Label(frame, text="", anchor="center")
        self.preview_result.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_table(self, parent):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ("file", "status", "count", "source")
        self.table = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        headings = {"file": "File", "status": "Status", "count": "Colonies", "source": "Source"}
        widths = {"file": 260, "status": 120, "count": 100, "source": 520}
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
            title="Select colony images",
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
            self.table.insert("", "end", iid=item_id, values=(os.path.basename(path), "Ready", "", path))
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
        self.preview_display_path = None
        self.preview_photo = None
        self.preview_generation += 1
        for item in self.table.get_children():
            self.table.delete(item)
        self.preview_title.config(text="Live Preview")
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(20, 20, text="Select a row to tune this image.", anchor="nw", fill="#5f6b7a")
        self.preview_result.config(text="")
        self.preview_status.config(text="")
        self.progress["value"] = 0
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
        self.batch_thread = threading.Thread(target=self._batch_worker, args=(settings,), daemon=True)
        self.batch_thread.start()

    def _batch_worker(self, settings):
        for index, image_path in enumerate(self.image_paths):
            self.event_queue.put(("status", index, "Running"))
            result = self._count_path(index, image_path, settings, self.output_dir_var.get(), colony_output_filename_for(image_path))
            if result:
                result["Source_Path"] = image_path
                result["Status"] = "Success"
                self.event_queue.put(("result", index, result))
            else:
                self.event_queue.put(("status", index, "Failed"))
            self.event_queue.put(("progress", index + 1))
        self.event_queue.put(("batch_done",))

    def _count_path(self, index, image_path, settings, output_dir, output_filename):
        os.makedirs(output_dir, exist_ok=True)
        return count_colonies.process_image(
            image_path,
            output_dir,
            binary_threshold=settings["binary_threshold"],
            erosion_iterations=settings["erosion_iterations"],
            min_solidity=settings["min_solidity"],
            min_colony_area=settings["min_colony_area"],
            max_colony_area=settings["max_colony_area"],
            output_filename=output_filename,
            return_details=True,
        )

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
            self.update_row(index, result["Status"], result["Colony_Count"])
            if result["Source_Path"] == self.preview_path:
                self.apply_preview_result(result)
            self.write_current_csv()
        elif kind == "progress":
            self.progress["value"] = event[1]
            self._set_status(f"Counted {event[1]} of {len(self.image_paths)} image(s).")
        elif kind == "batch_done":
            self.batch_thread = None
            self.run_button.state(["!disabled"])
            self._set_status(f"Finished: {len(self.results_by_path)} colony count result(s).")
        elif kind == "preview_result":
            _, generation, result = event
            if generation == self.preview_generation:
                if result:
                    self.apply_preview_result(result)
                else:
                    self.preview_result.config(text="Preview failed. Check plate detection or colony settings.")
        elif kind == "preview_done":
            _, generation = event
            if generation == self.preview_generation:
                self.preview_thread = None
                self.preview_status.config(text="")
                if self.preview_pending:
                    self.preview_pending = False
                    self.schedule_live_preview(delay=250)

    def update_row(self, index, status=None, count=""):
        item_id = str(index)
        if not self.table.exists(item_id):
            return
        values = list(self.table.item(item_id, "values"))
        if status:
            values[1] = status
        values[2] = count
        self.table.item(item_id, values=values)

    def on_row_selected(self, _event=None):
        selection = self.table.selection()
        if not selection:
            return
        self.set_preview_path(self.row_paths.get(selection[0]))

    def set_preview_path(self, path):
        if not path:
            return
        self.preview_path = path
        self.preview_title.config(text=os.path.basename(path))
        result = self.results_by_path.get(path)
        if result:
            self.apply_preview_result(result)
        else:
            self.preview_result.config(text="Live preview updates after settings settle.")
            self.schedule_live_preview(delay=150)

    def _bind_preview_traces(self):
        for variable in (
            self.binary_threshold_var,
            self.erosion_iterations_var,
            self.min_solidity_var,
            self.min_colony_area_var,
            self.max_colony_area_var,
        ):
            variable.trace_add("write", lambda *_: self.schedule_live_preview())
        self.preview_contrast_var.trace_add("write", self.on_preview_contrast_changed)

    def on_preview_contrast_changed(self, *_):
        if self.preview_contrast_rounding:
            return
        try:
            current_value = float(self.preview_contrast_var.get())
        except (tk.TclError, ValueError):
            return
        rounded_value = round(current_value, 1)
        if abs(current_value - rounded_value) > 0.00001:
            self.preview_contrast_rounding = True
            self.preview_contrast_var.set(rounded_value)
            self.preview_contrast_rounding = False
        self.refresh_preview_display()

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
        os.makedirs(COLONY_PREVIEW_DIR, exist_ok=True)
        self.preview_generation += 1
        generation = self.preview_generation
        image_path = self.preview_path
        self.preview_status.config(text="Updating...")
        self.preview_thread = threading.Thread(target=self._preview_worker, args=(generation, image_path, settings), daemon=True)
        self.preview_thread.start()

    def _preview_worker(self, generation, image_path, settings):
        output_filename = colony_preview_filename_for(image_path)
        result = self._count_path(0, image_path, settings, COLONY_PREVIEW_DIR, output_filename)
        if result:
            result["Source_Path"] = image_path
            result["Status"] = "Preview"
        self.event_queue.put(("preview_result", generation, result))
        self.event_queue.put(("preview_done", generation))

    def apply_preview_result(self, result):
        output_path = result.get("Output_Path")
        if output_path:
            self.load_preview_image(output_path)
        self.preview_result.config(text=f"Colonies: {result.get('Colony_Count', '')}")

    def load_preview_image(self, path):
        if not path or not os.path.exists(path):
            return
        self.preview_display_path = path
        self.refresh_preview_display()

    def refresh_preview_display(self):
        path = self.preview_display_path
        if not path or not os.path.exists(path):
            return
        try:
            max_w = max(360, self.preview_canvas.winfo_width() - 20)
            max_h = max(280, self.preview_canvas.winfo_height() - 20)
            if Image is not None and ImageTk is not None and ImageEnhance is not None:
                image = Image.open(path).convert("RGB")
                contrast = float(self.preview_contrast_var.get())
                image = ImageEnhance.Contrast(image).enhance(contrast)
                image.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                self.preview_photo = ImageTk.PhotoImage(image)
            else:
                photo = tk.PhotoImage(file=path)
                shrink = max(1, int(max(photo.width() / max_w, photo.height() / max_h)))
                if shrink > 1:
                    photo = photo.subsample(shrink, shrink)
                self.preview_photo = photo
            self.preview_canvas.delete("all")
            canvas_w = max(1, self.preview_canvas.winfo_width())
            canvas_h = max(1, self.preview_canvas.winfo_height())
            x = max(0, (canvas_w - self.preview_photo.width()) // 2)
            y = max(0, (canvas_h - self.preview_photo.height()) // 2)
            self.preview_canvas.create_image(x, y, image=self.preview_photo, anchor="nw")
        except (tk.TclError, OSError, ValueError) as exc:
            self.preview_canvas.delete("all")
            self.preview_canvas.create_text(20, 20, text=f"Preview unavailable: {exc}", anchor="nw", fill="#5f6b7a")

    def settings(self):
        return {
            "binary_threshold": int(float(self.binary_threshold_var.get())),
            "erosion_iterations": int(float(self.erosion_iterations_var.get())),
            "min_solidity": float(self.min_solidity_var.get()),
            "min_colony_area": float(self.min_colony_area_var.get()),
            "max_colony_area": float(self.max_colony_area_var.get()),
        }

    def write_current_csv(self):
        rows = [self.results_by_path[path] for path in self.image_paths if path in self.results_by_path]
        if rows:
            write_colony_csv(os.path.join(self.output_dir_var.get(), "colony_counts.csv"), rows)

    def open_output_dir(self):
        os.makedirs(self.output_dir_var.get(), exist_ok=True)
        subprocess.run(["open", self.output_dir_var.get()], check=False)

    def is_busy(self):
        return self.batch_thread is not None and self.batch_thread.is_alive()

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
        "--method",
        "auto",
        "--output-dir",
        output_dir,
        "--output-filename",
        output_filename,
        "--plate-diameter-cm",
        str(settings["plate_diameter_cm"]),
        "--sensitivity",
        str(settings["sensitivity"]),
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
    return f"{stem}_analyzed.png"


def preview_filename_for(index, path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"preview_{index + 1:03d}_{stem}.png"


def manual_output_filename_for(index, path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"{stem}_analyzed.png"


def colony_output_filename_for(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"{stem}_colonies_counted.png"


def colony_preview_filename_for(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"preview_{stem}_colonies_counted.png"


def write_csv(path, rows):
    fieldnames = ["Filename", "Source_Path", "Status", "Method", "Sensitivity", "Max_Diameter_cm", "Min_Diameter_cm", "Area_cm2", "Pixel_to_CM_Ratio", "Output_Path"]
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def write_colony_csv(path, rows):
    fieldnames = [
        "Filename",
        "Source_Path",
        "Status",
        "Colony_Count",
        "Binary_Threshold",
        "Erosion_Iterations",
        "Min_Solidity",
        "Min_Colony_Area",
        "Max_Colony_Area",
        "Output_Path",
    ]
    with open(path, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


if __name__ == "__main__":
    log_startup(f"Starting Tk UI with {sys.executable}")
    root = tk.Tk()
    log_startup("Tk root created")
    app = ProgramLauncher(root)
    log_startup("GUI built; entering mainloop")
    root.mainloop()
    log_startup("Mainloop exited")
