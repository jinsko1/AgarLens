# AgarLens

AgarLens is a local desktop app for agar plate image analysis. It currently includes:

- Swim Diameter Analyzer
- Colony Counter powered by a trained YOLO model

The app is written in Python/Tkinter and is intended to run locally, without a browser.

## Project Files

- `growth_analyzer_gui.py`: main desktop app
- `analysis_worker.py`: subprocess runner for swim diameter analysis
- `analyze_plates.py`: swim diameter backend
- `count_colonies_yolo.py`: YOLO colony-counting backend
- `count_colonies.py`: legacy OpenCV colony-counting backend kept for comparison
- `setup_mac.command`: one-time macOS setup for lab computers
- `run_growth_analyzer.command`: macOS double-click launcher
- `run_agarlens.sh`: macOS/Linux terminal launcher
- `run_agarlens.bat`: Windows launcher

## Required Model

The colony counter expects the trained YOLO model at:

```text
runs/detect/train-5/weights/best.pt
```

You can also keep the model somewhere else and set:

```bash
export AGARLENS_MODEL_PATH="/path/to/best.pt"
```

On Windows:

```bat
set AGARLENS_MODEL_PATH=C:\path\to\best.pt
```

## Setup

Use Python 3.10 or newer when possible.

For a Mac lab computer, the easiest path is to double-click:

```text
setup_mac.command
```

That creates the local `venv` and installs the required packages once. After setup, users should launch the app with `run_growth_analyzer.command`.

Manual macOS/Linux setup:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows:

```bat
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## Run

macOS double-click:

```text
run_growth_analyzer.command
```

macOS/Linux terminal:

```bash
./run_agarlens.sh
```

Windows:

```bat
run_agarlens.bat
```

Direct Python:

```bash
python growth_analyzer_gui.py
```

## Build A Mac App

This is only for making a release bundle. Normal users should not do this.

After setup, install PyInstaller and run the build script:

```bash
source venv/bin/activate
python -m pip install pyinstaller
./build_mac_app.sh
```

The app bundle is created at:

```text
dist/AgarLens.app
```

The bundled app is large because it includes Python, OpenCV, Torch, Ultralytics, and the YOLO model. On this machine the first build was about 750 MB. For sharing outside your own Mac, the app may still need proper Apple Developer signing/notarization.

## Notes For Sharing

- For other lab Macs, share the project folder, include `best.pt`, run `setup_mac.command` once, then use `run_growth_analyzer.command`.
- For public distribution, build the app once and upload `AgarLens.app` as a GitHub Release. Do not ask users to run PyInstaller.
- Keep generated outputs out of Git.
- Include the YOLO `best.pt` model separately unless you deliberately want it tracked.
- The launchers use the Python interpreter from the local virtual environment when available.
- Output folders, logs, model artifacts, and caches are ignored by `.gitignore`.
