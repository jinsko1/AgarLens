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

## Notes For Sharing

- Share the project folder, but keep generated outputs out of Git.
- Include the YOLO `best.pt` model separately unless you deliberately want it tracked.
- The app now uses the Python interpreter from the active virtual environment when available.
- Output folders, logs, model artifacts, and caches are ignored by `.gitignore`.
