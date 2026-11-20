# Claudy 1.7 — AI Vision & Capturer Suite

Open-source desktop vision loader, real-time YOLOv11 DirectML overlay, and dataset capturer/labeling toolkit built with **HTML5/Edge WebView2**, **Python**, and a **native C++ launcher**.

## Features
- **HTML5 / WebView2 Modern UI** (`claudy_ui.html` + `rob_run_loader.py`):
  - Light, Dark, and System themes with live custom accent color picker.
  - Custom ESP & FOV color pickers with real-time HTML5 Canvas preview.
  - Preset manager with `ROBRUN_V7:...` shareable config codes and live 0.25s hot-reload.
- **High-Speed DirectML Overlay** (`live_overlay.py`):
  - Powered by **YOLOv11 v7 ONNX (FP16)** on `DmlExecutionProvider` (~68+ FPS inference).
  - Click-through transparent top-most window (`WS_EX_TRANSPARENT` + `WDA_EXCLUDEFROMCAPTURE`).
- **Dataset & Training Tools**:
  - `label_tool.py` — Fast bounding-box annotation tool.
  - `live_preview.py` — Real-time OpenCV detection preview.
  - `yt_downloader.py` — YouTube clip downloader for dataset expansion.

## Building from Source (Windows)
1. Install Python 3.12+ and dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run directly:
   ```bash
   python rob_run_loader.py
   ```
3. Build standalone `.exe`:
   ```bash
   python -m PyInstaller --noconfirm --onefile --noconsole --noupx --name "Claudy_v7_Portable" --icon "assets/claudy.ico" --version-file "version_info.txt" --add-data "claudy_ui.html;." --add-data "assets;assets" --add-data "runs/player_v7/weights/best_640.onnx;runs/player_v7/weights" --collect-all webview --collect-all onnxruntime rob_run_loader.py
   ```

## License
Licensed under the [MIT License](LICENSE).
