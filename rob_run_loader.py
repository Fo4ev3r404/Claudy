import sys

# CRITICAL: If launched with --overlay, run pure live_overlay immediately BEFORE importing webview/.NET CLR!
if "--overlay" in sys.argv:
    import live_overlay
    live_overlay.main()
    sys.exit(0)

import base64
import ctypes
import json
import math
import os
import subprocess
import threading
import time
import psutil
import webview

if False:
    # Keep hints for PyInstaller analysis without importing them into the GUI Loader process
    import cv2
    import mss
    import numpy as np
    import onnxruntime as ort
    from PIL import ImageGrab
    import live_overlay

if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(sys.executable)
    MEIPASS_DIR = getattr(sys, "_MEIPASS", EXE_DIR)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))
    MEIPASS_DIR = EXE_DIR

APP_DIR = EXE_DIR if os.path.exists(os.path.join(EXE_DIR, "runs")) else MEIPASS_DIR
CONFIG_PATH = os.path.join(EXE_DIR if getattr(sys, "frozen", False) else APP_DIR, "loader_config.json")


def resolve_asset(rel_path):
    for root in (EXE_DIR, MEIPASS_DIR, APP_DIR):
        p = os.path.join(root, rel_path)
        if os.path.exists(p):
            return p
    return os.path.join(APP_DIR, rel_path)


HTML_PATH = resolve_asset("claudy_ui.html")
ICO_PATH = resolve_asset(os.path.join("assets", "claudy.ico"))
WINDOW_TITLE = "Claudy 1.7 // Rob Run AI v7"
LOCKED_MODEL_VERSION = "player_v7"

try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Claudy.RobRun.AI.v7")
except Exception:
    pass


def apply_win11_styling_and_icon():
    """Applies Claudy.ico to Win32 HWND (Big & Small icons + Class icon) and enables Windows 11 native rounded corners."""
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    for _ in range(50):
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if hwnd:
            try:
                pref = ctypes.c_int(2)
                dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(pref), ctypes.sizeof(pref))
            except Exception:
                pass

            if os.path.exists(ICO_PATH):
                try:
                    hicon_big = user32.LoadImageW(0, ICO_PATH, 1, 64, 64, 0x0010)
                    hicon_small = user32.LoadImageW(0, ICO_PATH, 1, 32, 32, 0x0010)
                    if hicon_big:
                        user32.SendMessageW(hwnd, 0x0080, 1, hicon_big)
                        user32.SetClassLongPtrW(hwnd, -14, hicon_big)
                    if hicon_small:
                        user32.SendMessageW(hwnd, 0x0080, 0, hicon_small)
                        user32.SetClassLongPtrW(hwnd, -34, hicon_small)
                except Exception:
                    pass
            break
        time.sleep(0.1)


def get_runner_command(script_name):
    if getattr(sys, "frozen", False):
        if script_name == "live_overlay.py":
            return [sys.executable, "--overlay"]
    cpp_exe = os.path.join(APP_DIR, "Claudy_v7.exe")
    if script_name == "live_overlay.py" and os.path.exists(cpp_exe):
        return [cpp_exe, "--overlay"]
    py_exe = r"C:\Python314\pythonw.exe" if os.path.exists(r"C:\Python314\pythonw.exe") else sys.executable
    return [py_exe, os.path.join(APP_DIR, script_name)]


def get_visible_window_titles():
    titles = []
    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    GetWindowText = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible

    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLength(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                GetWindowText(hwnd, buff, length + 1)
                if buff.value:
                    titles.append(buff.value)
        return True

    try:
        EnumWindows(EnumWindowsProc(foreach_window), 0)
    except Exception:
        pass
    return titles


def check_game_running(keywords_str):
    keywords = [k.strip().lower() for k in keywords_str.split(",") if k.strip()]
    if not keywords:
        keywords = ["robrun", "rob run", "looty bay", "lootybay"]

    for title in get_visible_window_titles():
        tl = title.lower()
        if "claudy" in tl or "robrun ai" in tl:
            continue
        for kw in keywords:
            if kw in tl:
                return True, f"Window: {title}"

    try:
        for proc in psutil.process_iter(["name"]):
            pname = (proc.info.get("name") or "").lower()
            if "robrun_loader" in pname or "claudy" in pname:
                continue
            for kw in keywords:
                kw_nospace = kw.replace(" ", "")
                if kw in pname or (kw_nospace and kw_nospace in pname):
                    return True, f"Process: {proc.info.get('name')}"
    except Exception:
        pass
    return False, ""


def get_default_config():
    default_s = {
        "preset_name": "Default (Balanced v7)",
        "model_version": LOCKED_MODEL_VERSION,
        "aim_enabled": True,
        "center_mode": True,
        "aim_key": "RMB (Right Click)",
        "aim_fov": 100,
        "smooth_x": 0.82,
        "smooth_y": 0.65,
        "head_ratio": 0.18,
        "deadzone_x": 2.0,
        "deadzone_y": 2.0,
        "max_step": 150,
        "recoil_enabled": True,
        "recoil_strength": 65.0,
        "conf_thresh": 0.28,
        "iou_thresh": 0.45,
        "box_style": "Corners",
        "esp_color": "#2986E2",
        "fov_color": "#2986E2",
        "head_dot_color": "#FF2E43",
        "show_head_dot": True,
        "show_fov": True,
        "show_labels": True,
        "show_hud": True,
        "show_snaplines": False,
    }
    return {
        "active_preset": "Default (Balanced v7)",
        "ui_theme": "dark",
        "wait_mode": "Smart Wait (Auto-Start after 3.5s)",
        "target_process": "RobRun, Rob Run, Looty Bay",
        "active_settings": dict(default_s),
        "presets": {
            "Default (Balanced v7)": dict(default_s),
            "Legit / Silent Smooth": {
                **default_s,
                "preset_name": "Legit / Silent Smooth",
                "aim_fov": 75,
                "smooth_x": 0.45,
                "smooth_y": 0.36,
                "head_ratio": 0.20,
                "deadzone_x": 2.5,
                "deadzone_y": 2.5,
                "max_step": 90,
                "recoil_strength": 50.0,
            },
            "Rage / Instant Lock": {
                **default_s,
                "preset_name": "Rage / Instant Lock",
                "aim_fov": 185,
                "smooth_x": 0.96,
                "smooth_y": 0.86,
                "head_ratio": 0.17,
                "deadzone_x": 1.0,
                "deadzone_y": 1.0,
                "max_step": 240,
                "recoil_strength": 78.0,
                "show_snaplines": True,
            },
            "Sniper / Head Tap": {
                **default_s,
                "preset_name": "Sniper / Head Tap",
                "aim_fov": 60,
                "smooth_x": 0.88,
                "smooth_y": 0.78,
                "head_ratio": 0.15,
                "deadzone_x": 1.0,
                "deadzone_y": 1.0,
                "recoil_enabled": False,
                "recoil_strength": 0.0,
            },
            "Spray / Recoil Pro": {
                **default_s,
                "preset_name": "Spray / Recoil Pro",
                "aim_fov": 125,
                "smooth_x": 0.78,
                "smooth_y": 0.68,
                "head_ratio": 0.27,
                "recoil_enabled": True,
                "recoil_strength": 95.0,
            },
        },
    }


class ClaudyBridgeAPI:
    def __init__(self):
        self._window = None
        self._maximized = False
        self._overlay_proc = None
        self._waiting_for_game = False
        self._cancel_wait_flag = False
        self._skip_wait_flag = False
        self._config_data = self._load_config()

        threading.Thread(target=self._monitor_overlay_loop, daemon=True).start()

    def _load_config(self):
        data = get_default_config()
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                data.update(loaded)
                if "active_settings" in loaded:
                    merged = dict(get_default_config()["active_settings"])
                    merged.update(loaded["active_settings"])
                    data["active_settings"] = merged
                if not data.get("presets"):
                    data["presets"] = get_default_config()["presets"]
            except Exception:
                pass
        data["active_settings"]["model_version"] = LOCKED_MODEL_VERSION
        for p in data.get("presets", {}).values():
            p["model_version"] = LOCKED_MODEL_VERSION
        return data

    def _save_config(self):
        self._config_data["active_settings"]["model_version"] = LOCKED_MODEL_VERSION
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._config_data, f, indent=2)
        except Exception:
            pass

    def get_initial_state(self, _arg=None):
        self._config_data["active_settings"]["model_version"] = LOCKED_MODEL_VERSION
        return self._config_data

    def update_setting(self, payload):
        if not isinstance(payload, dict):
            return
        k = payload.get("key")
        v = payload.get("value")
        if not k or k == "model_version":
            return
        self._config_data["active_settings"][k] = v
        if k == "deadzone_x":
            self._config_data["active_settings"]["deadzone_y"] = v
        self._save_config()

    def set_theme(self, theme_name):
        self._config_data["ui_theme"] = theme_name
        self._save_config()

    def set_accent(self, hex_color):
        self._config_data["ui_accent"] = hex_color
        self._save_config()

    def set_wait_mode(self, mode):
        self._config_data["wait_mode"] = mode
        self._save_config()

    def set_target_proc(self, val):
        self._config_data["target_process"] = (val or "").strip() or "RobRun, Rob Run, Looty Bay"
        self._save_config()

    def select_preset(self, name):
        presets = self._config_data.get("presets", {})
        if name not in presets:
            return
        self._config_data["active_preset"] = name
        loaded = dict(presets[name])
        loaded["preset_name"] = name
        loaded["model_version"] = LOCKED_MODEL_VERSION
        self._config_data["active_settings"].update(loaded)
        self._save_config()
        self._push_state_to_js()

    def save_current_preset(self, _arg=None):
        name = self._config_data.get("active_preset", "Default (Balanced v7)")
        self._config_data["active_settings"]["preset_name"] = name
        self._config_data["active_settings"]["model_version"] = LOCKED_MODEL_VERSION
        self._config_data["presets"][name] = dict(self._config_data["active_settings"])
        self._save_config()
        self._push_state_to_js()

    def create_preset(self, name):
        if not name or not str(name).strip():
            return
        name = str(name).strip()
        self._config_data["active_settings"]["preset_name"] = name
        self._config_data["active_settings"]["model_version"] = LOCKED_MODEL_VERSION
        self._config_data["presets"][name] = dict(self._config_data["active_settings"])
        self._config_data["active_preset"] = name
        self._save_config()
        self._push_state_to_js()

    def delete_current_preset(self, _arg=None):
        presets = self._config_data.get("presets", {})
        if len(presets) <= 1:
            return
        cur = self._config_data.get("active_preset", "")
        presets.pop(cur, None)
        first = list(presets.keys())[0]
        self.select_preset(first)

    def export_preset(self, _arg=None):
        raw = json.dumps(self._config_data["active_settings"], separators=(",", ":")).encode("utf-8")
        return "ROBRUN_V7:" + base64.b64encode(raw).decode("ascii")

    def import_preset(self, code):
        if not code:
            return
        code = str(code).strip()
        if code.startswith("ROBRUN_V7:"):
            code = code[len("ROBRUN_V7:"):]
        try:
            decoded = json.loads(base64.b64decode(code.encode("ascii")).decode("utf-8"))
            p_name = decoded.get("preset_name") or f"Imported_{int(time.time()) % 1000}"
            merged = dict(get_default_config()["active_settings"])
            merged.update(decoded)
            merged["preset_name"] = p_name
            merged["model_version"] = LOCKED_MODEL_VERSION
            self._config_data["presets"][p_name] = merged
            self.select_preset(p_name)
        except Exception:
            pass

    def _push_state_to_js(self):
        if not self._window:
            return
        js_payload = json.dumps(self._config_data)
        try:
            self._window.evaluate_js(f"syncUIFromState({js_payload});")
        except Exception:
            pass

    def _push_status_to_js(self, state, title="", subtitle="", progress=0.0):
        if not self._window:
            return
        payload = json.dumps({
            "state": state,
            "title": title,
            "subtitle": subtitle,
            "progress": progress,
        })
        try:
            self._window.evaluate_js(f"window.updateLaunchStatus({payload});")
        except Exception:
            pass

    def _is_overlay_running(self):
        return self._overlay_proc is not None and self._overlay_proc.poll() is None

    def run_clicked(self, _arg=None):
        if self._is_overlay_running():
            self._stop_overlay()
            return
        if self._waiting_for_game:
            return

        self._save_config()
        wait_mode = self._config_data.get("wait_mode", "Smart Wait (Auto-Start after 3.5s)")
        if "Instant" in wait_mode:
            self._spawn_overlay()
            return

        self._waiting_for_game = True
        self._cancel_wait_flag = False
        self._skip_wait_flag = False
        threading.Thread(target=self._wait_for_game_worker, args=(wait_mode,), daemon=True).start()

    def skip_wait(self, _arg=None):
        self._skip_wait_flag = True

    def cancel_wait(self, _arg=None):
        self._cancel_wait_flag = True

    def _wait_for_game_worker(self, wait_mode):
        is_smart = "Smart" in wait_mode
        start_t = time.perf_counter()
        smart_dur = 3.5
        keywords = self._config_data.get("target_process", "RobRun, Rob Run, Looty Bay")

        step = 0
        while not self._cancel_wait_flag and not self._skip_wait_flag:
            el = time.perf_counter() - start_t
            found, _ = check_game_running(keywords)
            if found and el >= 1.2:
                break

            dots = "." * ((step % 3) + 1)
            if is_smart:
                prog = min(1.0, el / smart_dur)
                rem = max(0.0, smart_dur - el)
                self._push_status_to_js(
                    "waiting",
                    f"Waiting for game to start{dots}",
                    f"Scanning processes for Rob Run... (Injecting AI v7 in {rem:.1f}s)",
                    prog,
                )
                if el >= smart_dur:
                    break
            else:
                prog = (math.sin(el * 2.5) + 1.0) / 2.0
                self._push_status_to_js(
                    "waiting",
                    f"Waiting for game to start{dots}",
                    f"Waiting for Rob Run ({keywords}) window or click 'Skip Wait' below...",
                    prog,
                )
            step += 1
            time.sleep(0.12)

        self._waiting_for_game = False
        if self._cancel_wait_flag:
            self._push_status_to_js("standby")
            return
        self._spawn_overlay()

    def _spawn_overlay(self):
        self._save_config()
        cmd = get_runner_command("live_overlay.py")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self._overlay_proc = subprocess.Popen(cmd, cwd=APP_DIR, creationflags=flags)
            self._push_status_to_js("running")
            # Minimize WebView2 window while overlay runs so Chromium uses 0% GPU in-game
            if self._window:
                try:
                    self._window.minimize()
                except Exception:
                    pass
        except Exception:
            self._push_status_to_js("standby")

    def _stop_overlay(self):
        if self._is_overlay_running():
            try:
                self._overlay_proc.terminate()
                self._overlay_proc.wait(timeout=2)
            except Exception:
                try:
                    self._overlay_proc.kill()
                except Exception:
                    pass
        self._overlay_proc = None
        self._push_status_to_js("standby")

    def _monitor_overlay_loop(self):
        while True:
            if self._overlay_proc is not None and self._overlay_proc.poll() is not None:
                self._overlay_proc = None
                self._push_status_to_js("standby")
            time.sleep(0.6)

    def launch_tool(self, script_name):
        path = os.path.join(APP_DIR, str(script_name))
        if os.path.exists(path):
            subprocess.Popen(get_runner_command(str(script_name)), cwd=APP_DIR)

    def open_folder(self, rel_path):
        target = os.path.join(APP_DIR, str(rel_path)) if rel_path else APP_DIR
        if os.path.exists(target):
            os.startfile(target)

    def toggle_maximize(self, _arg=None):
        if not self._window:
            return
        if self._maximized:
            self._window.restore()
            self._maximized = False
        else:
            self._window.maximize()
            self._maximized = True

    def close_window(self, _arg=None):
        self._cancel_wait_flag = True
        self._save_config()
        if self._window:
            self._window.destroy()
        os._exit(0)


def main():
    if "--overlay" in sys.argv:
        live_overlay.main()
        return

    api = ClaudyBridgeAPI()
    win = webview.create_window(
        title=WINDOW_TITLE,
        url=HTML_PATH,
        js_api=api,
        width=1040,
        height=650,
        min_size=(960, 600),
        frameless=True,
        shadow=True,
        easy_drag=False,
        background_color="#0E0F11",
    )
    api._window = win
    threading.Thread(target=apply_win11_styling_and_icon, daemon=True).start()
    webview.start(gui="edgechromium", debug=False, icon=ICO_PATH if os.path.exists(ICO_PATH) else None)


if __name__ == "__main__":
    main()
