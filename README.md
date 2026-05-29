# AgarLens

AgarLens is a local desktop app for analyzing agar plate images. It currently includes two workflows:

- **Swim Diameter Analyzer**: measures growth diameter and area from scanned agar plate images.
- **Colony Counter**: counts bacterial colonies with a trained YOLO model while rejecting detections outside the Petri dish.

The app runs locally with a Tkinter interface. It does not require a browser or internet connection after setup.

## What The App Does

### Swim Diameter Analyzer

The swim diameter tool detects the plate, identifies the growth region, measures the maximum and minimum diameter, estimates growth area, and saves:

- annotated plate images
- `growth_analysis_results.csv`

The user can manually adjust the measured ellipse when the automatic measurement needs correction.

### Colony Counter

The colony counter uses a trained YOLO model at:

```text
runs/detect/train-5/weights/best.pt
```

The backend first detects the Petri dish, masks out everything outside the plate, runs YOLO on the masked plate image, rejects detections outside the valid plate region, and saves:

- annotated colony images
- `colony_counts.csv`

Plates with more than 300 colonies are reported as:

```text
Too many to count (>300)
```

## Recommended Installation

For normal users, use the files from the GitHub **Releases** page, not the green "Code" button.

Download the release file for your operating system:

```text
AgarLens_macOS_*.zip       macOS
AgarLens_Windows_*.zip     Windows
```

GitHub also shows "Source code ZIP/TAR" automatically. Those are not the normal app downloads.

## macOS Setup

1. Download `AgarLens_macOS_*.zip` from the latest GitHub Release.
2. Unzip it.
3. Double-click:

```text
setup_mac.command
```

4. Wait for setup to finish. It creates a local `venv` and installs the required Python packages.
5. Launch AgarLens by double-clicking:

```text
run_growth_analyzer.command
```

If macOS blocks the command file because it was downloaded from the internet, right-click the file, choose **Open**, then confirm.

## Windows Setup

1. Download `AgarLens_Windows_*.zip` from the latest GitHub Release.
2. Unzip it.
3. Double-click:

```text
setup_windows.bat
```

4. Wait for setup to finish. It creates a local `venv` and installs the required Python packages.
5. Launch AgarLens by double-clicking:

```text
run_agarlens.bat
```

## Manual Setup From Source

Use this path if you are developing the app or running directly from the repository.

Python 3.10 or newer is recommended.

macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python growth_analyzer_gui.py
```

Windows:

```bat
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python growth_analyzer_gui.py
```

## How To Use

1. Open AgarLens.
2. Choose either **Swim Diameter Program** or **Colony Counter Program**.
3. Add individual images or add a folder of images.
4. Choose an output folder if you do not want to use the default output folder.
5. Run the batch analysis/count.
6. Review the annotated images and CSV output in the results folder.

For the swim diameter workflow, you can manually adjust the measurement ellipse if the automatic result is not satisfactory.

For the colony counter workflow, the trained YOLO model handles detection automatically. The app crops annotated outputs around the plate and stops counting once a plate is confirmed to have more than 300 colonies.

After a colony batch count finishes, select an analyzed image to correct the count manually. Click a red dot to remove that detected colony, or click an empty spot on the annotated image to add a colony. The displayed count, annotated image text, and `colony_counts.csv` update after each edit.

## Project Files

- `growth_analyzer_gui.py`: main desktop app and user interface
- `analysis_worker.py`: subprocess runner for swim diameter analysis
- `analyze_plates.py`: swim diameter backend
- `count_colonies_yolo.py`: YOLO colony-counting backend
- `count_colonies.py`: legacy OpenCV colony-counting backend kept for comparison
- `requirements.txt`: Python dependencies
- `setup_mac.command`: one-time macOS setup script
- `setup_windows.bat`: one-time Windows setup script
- `run_growth_analyzer.command`: macOS launcher
- `run_agarlens.sh`: macOS/Linux terminal launcher
- `run_agarlens.bat`: Windows launcher
- `make_user_bundle.sh`: creates platform-specific release ZIP files
- `build_launcher_app.sh`: creates a local clickable macOS launcher app

## YOLO Model Location

By default, the colony counter expects:

```text
runs/detect/train-5/weights/best.pt
```

If the model is somewhere else, set `AGARLENS_MODEL_PATH`.

macOS/Linux:

```bash
export AGARLENS_MODEL_PATH="/path/to/best.pt"
```

Windows:

```bat
set AGARLENS_MODEL_PATH=C:\path\to\best.pt
```

## Making GitHub Release ZIPs

Maintainers can create platform-specific release bundles with:

```bash
./make_user_bundle.sh
```

This creates files in `dist/` like:

```text
AgarLens_macOS_YYYYMMDD-HHMMSS.zip
AgarLens_Windows_YYYYMMDD-HHMMSS.zip
```

Upload those ZIP files to the GitHub Releases page.

## Building A Local macOS App Launcher

For your own Mac, you can create a clickable Dock/Finder app with:

```bash
./build_launcher_app.sh
```

This creates:

```text
dist/AgarLens.app
dist/AgarLens_Launcher_macOS.zip
```

This launcher app uses the local project folder and its `venv`. It is much faster and smaller than a fully standalone PyInstaller app, but it is not a self-contained app for other computers by itself. For other users, publish the release ZIPs from `make_user_bundle.sh`.

## Troubleshooting

### The colony counter takes a while on the first image

The YOLO model and Torch backend have to load the first time the colony counter page opens. The app warms the model in the background and keeps **Run Batch Count** disabled until the warmup finishes, so the first real image should no longer pay the model-loading cost.

### The colony counter says the model is missing

Make sure `best.pt` exists at:

```text
runs/detect/train-5/weights/best.pt
```

or set `AGARLENS_MODEL_PATH`.

### The setup script cannot find Python

Install Python 3.10 or newer, then run the setup script again.

### macOS will not open a `.command` file

Right-click the file, choose **Open**, then confirm. This is a standard macOS security step for downloaded scripts.

## Development Notes

Generated outputs, virtual environments, model artifacts, logs, and packaged release files are ignored by Git. Keep trained model files and release ZIPs out of normal commits unless you intentionally want to publish them as release assets.
