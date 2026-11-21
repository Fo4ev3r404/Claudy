import ctypes
import json
import math
import os
import sys
import threading
import time
import tkinter as tk
import cv2
import mss
import numpy as np
import onnxruntime as ort
from PIL import ImageGrab

# Force Per-Monitor DPI Awareness BEFORE mss or tkinter so 125%/150% Windows scaling never offsets ESP boxes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

if getattr(sys, "frozen", False):
    EXE_DIR = os.path.dirname(sys.executable)
    MEIPASS_DIR = getattr(sys, "_MEIPASS", EXE_DIR)
else:
    EXE_DIR = os.path.dirname(os.path.abspath(__file__))
    MEIPASS_DIR = EXE_DIR

APP_DIR = EXE_DIR if os.path.exists(os.path.join(EXE_DIR, "runs")) else MEIPASS_DIR
CONFIG_PATH = os.path.join(EXE_DIR if getattr(sys, "frozen", False) else APP_DIR, "loader_config.json")

# Fast direct module globals (zero dict-copy overhead in inference or draw loop)
PLAYER_CONF = 0.28
IOU_THRESH = 0.45
HEAD_Y_RATIO = 0.18       # 0.18 from top of player box = center of head/face

# Aim-to-dot settings (identical to original tuned values)
AIM_FOV_PX = 100          # Only track targets within this radius from screen center
AIM_SMOOTH_X = 0.82       # Snappy horizontal lock (synced 1:1 with fresh frames)
AIM_SMOOTH_Y = 0.65       # Snappy vertical lock (synced 1:1 with fresh frames)
AIM_X_DEADZONE = 2.0      # Ignore tiny <2px horizontal jitter on head
AIM_Y_DEADZONE = 2.0      # Ignore tiny <2px vertical jitter on head
AIM_MAX_STEP = 150        # Max pixels per tick for fast flicks
RECOIL_ENABLED = True
RECOIL_PX_PER_SEC = 65.0  # Downward pull (px/s) while holding Left Click

BOX_STYLE = "Corners"
ESP_COLOR = "#00FF88"
FOV_COLOR = "#FF4D4D"
HEAD_DOT_COLOR = "#FF2E43"
SHOW_HEAD_DOT = True
SHOW_FOV = True
SHOW_LABELS = True
SHOW_HUD = True
SHOW_SNAPLINES = False
PRESET_NAME = "Default (Balanced v7)"

TRANSPARENT_BG = "#000001"
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_XBUTTON1 = 0x05
VK_XBUTTON2 = 0x06
VK_SHIFT = 0x10
VK_MENU = 0x12
VK_F6 = 0x75
VK_F7 = 0x76
VK_F8 = 0x77
VK_F9 = 0x78
VK_END = 0x23

AIM_VK = VK_RBUTTON
AIM_KEY_MAP = {
    "RMB (Right Click)": VK_RBUTTON,
    "LMB (Left Click)": VK_LBUTTON,
    "Mouse 4 (Side)": VK_XBUTTON1,
    "Mouse 5 (Side)": VK_XBUTTON2,
    "Left Shift": VK_SHIFT,
    "Left Alt": VK_MENU,
}


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", INPUT_UNION)]


def move_mouse_rel(dx, dy):
    if dx == 0 and dy == 0:
        return
    extra = ctypes.c_ulong(0)
    inp = INPUT(
        type=0,
        union=INPUT_UNION(
            mi=MOUSEINPUT(
                dx=int(dx),
                dy=int(dy),
                mouseData=0,
                dwFlags=0x0001,
                time=0,
                dwExtraInfo=ctypes.pointer(extra),
            )
        ),
    )
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


class FastPreprocessor:
    """Preallocated letterbox + C++ cv2.dnn.blobFromImage."""
    def __init__(self, img_size, src_w, src_h):
        self.img_size = img_size
        self.scale = min(img_size / src_h, img_size / src_w)
        self.nh = int(round(src_h * self.scale))
        self.nw = int(round(src_w * self.scale))
        self.pad_w = (img_size - self.nw) // 2
        self.pad_h = (img_size - self.nh) // 2
        self.canvas = np.full((img_size, img_size, 3), 114, dtype=np.uint8)
        self.is_native = (src_w == img_size and src_h == img_size)

    def make_blob(self, frame_bgr):
        if self.is_native:
            return cv2.dnn.blobFromImage(frame_bgr, 1.0 / 255.0, (self.img_size, self.img_size), swapRB=True, crop=False)
        self.canvas[self.pad_h:self.pad_h + self.nh, self.pad_w:self.pad_w + self.nw] = cv2.resize(
            frame_bgr, (self.nw, self.nh), interpolation=cv2.INTER_NEAREST
        )
        return cv2.dnn.blobFromImage(self.canvas, 1.0 / 255.0, (self.img_size, self.img_size), swapRB=True, crop=False)


def run_from_blob(session, input_name, blob, prep, conf_thresh, target_classes=None, offset_x=0, offset_y=0):
    scale, pad_w, pad_h = prep.scale, prep.pad_w, prep.pad_h
    out = session.run(None, {input_name: blob})[0][0]  # (5+, 8400)

    if target_classes is None:
        scores = out[4, :]
        mask = scores >= conf_thresh
        if not np.any(mask):
            return []
        preds = out[:, mask].T
        scores = scores[mask]
        cls_ids = np.zeros(len(scores), dtype=np.int32)
    else:
        cls_scores = out[4:, :].T
        sub = cls_scores[:, target_classes]
        best_local = np.argmax(sub, axis=1)
        scores = sub[np.arange(len(sub)), best_local]
        mask = scores >= conf_thresh
        if not np.any(mask):
            return []
        preds = out[:, mask].T
        scores = scores[mask]
        cls_ids = np.array([target_classes[i] for i in best_local[mask]], dtype=np.int32)

    cx = preds[:, 0]
    cy = preds[:, 1]
    bw = preds[:, 2]
    bh = preds[:, 3]
    x1s = ((cx - bw * 0.5) - pad_w) / scale + offset_x
    y1s = ((cy - bh * 0.5) - pad_h) / scale + offset_y
    ws = bw / scale
    hs = bh / scale
    boxes_xywh = np.stack([x1s, y1s, ws, hs], axis=1).astype(np.int32).tolist()

    indices = cv2.dnn.NMSBoxes(boxes_xywh, scores.tolist(), conf_thresh, IOU_THRESH)
    results = []
    if len(indices) > 0:
        for idx in indices.flatten():
            x, y, w, h = boxes_xywh[idx]
            results.append((x, y, x + w, y + h, float(scores[idx]), int(cls_ids[idx])))
    return results


def is_own_player(x1, y1, x2, y2, scr_w, scr_h):
    cx = (x1 + x2) / 2.0
    w = x2 - x1
    h = y2 - y1
    if (0.14 * scr_w < cx < 0.58 * scr_w) and (y2 > 0.72 * scr_h) and (h > 0.20 * scr_h) and (w > 0.06 * scr_w):
        return True
    if (0.22 * scr_w < cx < 0.66 * scr_w) and (y2 > 0.85 * scr_h) and (h > 0.14 * scr_h):
        return True
    if (cx < 0.48 * scr_w) and (y1 > 0.45 * scr_h) and (y2 > 0.80 * scr_h) and (w > 0.09 * scr_w):
        return True
    if (0.36 * scr_w < cx < 0.64 * scr_w) and (y1 > 0.54 * scr_h) and (y2 > 0.66 * scr_h):
        return True
    return False


class PlayerSmoother:
    """Assigns stable track IDs, smooths box jitter, and bridges brief missed detections."""
    def __init__(self):
        self.tracks = []
        self.next_id = 1

    def update(self, dets):
        matched = set()
        new_tracks = []

        for tr in self.tracks:
            best_i = -1
            best_d = 100.0
            for i, (x1, y1, x2, y2, conf, cls_id) in enumerate(dets):
                if i in matched:
                    continue
                cx = (x1 + x2) / 2.0
                cy = (y1 + y2) / 2.0
                d = math.hypot(cx - tr["cx"], cy - tr["cy"])
                if d < best_d:
                    best_d = d
                    best_i = i

            if best_i >= 0:
                matched.add(best_i)
                x1, y1, x2, y2, conf, cls_id = dets[best_i]
                sx1, sy1, sx2, sy2 = x1, y1, x2, y2
                new_tracks.append({
                    "id": tr["id"],
                    "cx": (sx1 + sx2) / 2.0,
                    "cy": (sy1 + sy2) / 2.0,
                    "box": (sx1, sy1, sx2, sy2, conf, cls_id),
                    "hits": min(12, tr["hits"] + 1),
                    "missed": 0,
                })
            elif tr["missed"] < 10 and tr["hits"] >= 2:
                new_tracks.append({
                    "id": tr["id"],
                    "cx": tr["cx"],
                    "cy": tr["cy"],
                    "box": tr["box"],
                    "hits": tr["hits"],
                    "missed": tr["missed"] + 1,
                })

        for i, (x1, y1, x2, y2, conf, cls_id) in enumerate(dets):
            if i not in matched:
                new_tracks.append({
                    "id": self.next_id,
                    "cx": (x1 + x2) / 2.0,
                    "cy": (y1 + y2) / 2.0,
                    "box": (x1, y1, x2, y2, conf, cls_id),
                    "hits": 1,
                    "missed": 0,
                })
                self.next_id += 1

        self.tracks = new_tracks
        # Only return fresh detections (missed == 0) so ESP boxes NEVER lag behind moving players!
        return [
            (tr["id"], tr["box"], tr["missed"])
            for tr in self.tracks
            if tr["missed"] == 0
        ]


def draw_corner_box(canvas, x1, y1, x2, y2, box_color="#00FF88", corner_color="#FFFFFF"):
    """Draw a sleek ESP rectangle with bright corner brackets."""
    if BOX_STYLE == "Hidden":
        return
    if BOX_STYLE == "Full Box":
        canvas.create_rectangle(x1, y1, x2, y2, outline=box_color, width=1)
        return
    w = max(8.0, x2 - x1)
    h = max(12.0, y2 - y1)
    c = max(6.0, min(18.0, w * 0.28, h * 0.22))

    # Draw crisp corner brackets only (keeps player silhouette unobstructed)
    for px, py, dx, dy in (
        (x1, y1, 1, 1),
        (x2, y1, -1, 1),
        (x1, y2, 1, -1),
        (x2, y2, -1, -1),
    ):
        canvas.create_line(px, py, px + dx * c, py, fill=box_color, width=2)
        canvas.create_line(px, py, px, py + dy * c, fill=box_color, width=2)


def make_clickthrough(hwnd):
    user32 = ctypes.windll.user32
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOPMOST = 0x00000008
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000

    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd,
        GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
    )
    HWND_TOPMOST = -1
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOACTIVATE = 0x0010
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    WDA_EXCLUDEFROMCAPTURE = 0x00000011
    WDA_MONITOR = 0x00000001
    try:
        ok = user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        if not ok:
            user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
    except Exception:
        pass


def resolve_model_paths():
    p960_found = None
    p640_found = None
    for root in (EXE_DIR, APP_DIR, MEIPASS_DIR):
        weights_dir = os.path.join(root, "runs", "player_v7", "weights")
        cand_960 = os.path.join(weights_dir, "best.onnx")
        cand_640 = os.path.join(weights_dir, "best_640.onnx")
        if p960_found is None and os.path.exists(cand_960):
            p960_found = cand_960
        if p640_found is None and os.path.exists(cand_640):
            p640_found = cand_640
    return p960_found, p640_found


def apply_config_to_globals(state=None):
    global PLAYER_CONF, IOU_THRESH, HEAD_Y_RATIO, AIM_FOV_PX, AIM_SMOOTH_X, AIM_SMOOTH_Y
    global AIM_X_DEADZONE, AIM_Y_DEADZONE, AIM_MAX_STEP, RECOIL_ENABLED, RECOIL_PX_PER_SEC
    global BOX_STYLE, ESP_COLOR, FOV_COLOR, HEAD_DOT_COLOR, SHOW_HEAD_DOT, SHOW_FOV
    global SHOW_LABELS, SHOW_HUD, SHOW_SNAPLINES, PRESET_NAME, AIM_VK

    if not os.path.exists(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        c = data.get("active_settings", data)
        PLAYER_CONF = float(c.get("conf_thresh", PLAYER_CONF))
        IOU_THRESH = float(c.get("iou_thresh", IOU_THRESH))
        HEAD_Y_RATIO = float(c.get("head_ratio", HEAD_Y_RATIO))
        AIM_FOV_PX = int(c.get("aim_fov", AIM_FOV_PX))
        AIM_SMOOTH_X = float(c.get("smooth_x", AIM_SMOOTH_X))
        AIM_SMOOTH_Y = float(c.get("smooth_y", AIM_SMOOTH_Y))
        AIM_X_DEADZONE = float(c.get("deadzone_x", AIM_X_DEADZONE))
        AIM_Y_DEADZONE = float(c.get("deadzone_y", AIM_X_DEADZONE))
        AIM_MAX_STEP = int(c.get("max_step", AIM_MAX_STEP))
        RECOIL_ENABLED = bool(c.get("recoil_enabled", RECOIL_ENABLED))
        RECOIL_PX_PER_SEC = float(c.get("recoil_strength", RECOIL_PX_PER_SEC))
        BOX_STYLE = str(c.get("box_style", BOX_STYLE))
        ESP_COLOR = str(c.get("esp_color", ESP_COLOR))
        FOV_COLOR = str(c.get("fov_color", FOV_COLOR))
        HEAD_DOT_COLOR = str(c.get("head_dot_color", HEAD_DOT_COLOR))
        SHOW_HEAD_DOT = bool(c.get("show_head_dot", SHOW_HEAD_DOT))
        SHOW_FOV = bool(c.get("show_fov", SHOW_FOV))
        SHOW_LABELS = bool(c.get("show_labels", SHOW_LABELS))
        SHOW_HUD = bool(c.get("show_hud", SHOW_HUD))
        SHOW_SNAPLINES = bool(c.get("show_snaplines", SHOW_SNAPLINES))
        PRESET_NAME = str(data.get("active_preset", c.get("preset_name", PRESET_NAME)))
        AIM_VK = AIM_KEY_MAP.get(c.get("aim_key", "RMB (Right Click)"), VK_RBUTTON)
        if state is not None:
            state["aim_enabled"] = bool(c.get("aim_enabled", True))
            state["center_mode"] = bool(c.get("center_mode", True))
    except Exception:
        pass


def main():
    apply_config_to_globals()
    p960_path, p640_path = resolve_model_paths()

    opts = ort.SessionOptions()
    opts.enable_mem_pattern = False
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    providers = [("DmlExecutionProvider", {"device_id": 0}), "CPUExecutionProvider"]

    # Load only the primary 640 session into DirectML GPU VRAM at startup for maximum FPS & zero VRAM contention!
    # Lazy-load 960 session only if user presses F6 to switch to Full 960 mode.
    p640_sess = ort.InferenceSession(p640_path or p960_path, sess_options=opts, providers=providers)
    p640_inp = p640_sess.get_inputs()[0].name

    p960_holder = {"sess": None, "inp": None}

    def get_p960():
        if p960_holder["sess"] is None:
            if p960_path and os.path.exists(p960_path):
                s = ort.InferenceSession(p960_path, sess_options=opts, providers=providers)
                p960_holder["sess"] = s
                p960_holder["inp"] = s.get_inputs()[0].name
            else:
                p960_holder["sess"] = p640_sess
                p960_holder["inp"] = p640_inp
        return p960_holder["sess"], p960_holder["inp"]

    with mss.MSS() as sct:
        mon = sct.monitors[1]
        scr_w, scr_h = mon["width"], mon["height"]
        scr_x, scr_y = mon["left"], mon["top"]

    center_x = scr_w / 2.0
    center_y = scr_h / 2.0

    crop_w = min(640, scr_w)
    crop_h = min(640, scr_h)
    crop_left = (scr_w - crop_w) // 2
    crop_top = (scr_h - crop_h) // 2
    crop_mon = {
        "left": scr_x + crop_left,
        "top": scr_y + crop_top,
        "width": crop_w,
        "height": crop_h,
    }

    state = {
        "players": [],
        "fps": 0.0,
        "running": True,
        "aim_enabled": True,
        "center_mode": True,
        "draw_seq": 0,
    }
    apply_config_to_globals(state)

    lock = threading.Lock()
    player_smoother = PlayerSmoother()

    has_real_960 = bool(p960_path and os.path.exists(p960_path))
    prep_960 = FastPreprocessor(960 if has_real_960 else 640, scr_w, scr_h)
    prep_640 = FastPreprocessor(640, crop_w, crop_h)

    cap_lock = threading.Lock()
    cap_state = {"player_blob": None, "seq": 0, "is_center": True}
    cap_event = threading.Event()
    req_event = threading.Event()
    req_event.set()  # Request first frame immediately

    def config_watcher():
        last_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0.0
        while state["running"]:
            try:
                if os.path.exists(CONFIG_PATH):
                    mtime = os.path.getmtime(CONFIG_PATH)
                    if mtime != last_mtime:
                        last_mtime = mtime
                        apply_config_to_globals(state)
            except Exception:
                pass
            time.sleep(0.35)

    def capture_worker():
        seq = 0
        with mss.MSS() as sct:
            full_mon = sct.monitors[1]
            while state["running"]:
                # Wait until inference_worker is ready for a fresh frame (zero buffered stale frames!)
                if not req_event.wait(timeout=0.05):
                    continue
                req_event.clear()

                is_center = state["center_mode"]
                target_mon = crop_mon if is_center else full_mon
                try:
                    raw = np.asarray(sct.grab(target_mon))
                    frame = raw[:, :, :3]
                except Exception:
                    try:
                        pil_img = ImageGrab.grab()
                        full_f = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
                        frame = (
                            full_f[crop_top:crop_top + crop_h, crop_left:crop_left + crop_w]
                            if is_center
                            else full_f
                        )
                    except Exception:
                        time.sleep(0.02)
                        req_event.set()
                        continue

                p_blob = prep_640.make_blob(frame) if is_center else prep_960.make_blob(frame)
                seq += 1
                with cap_lock:
                    cap_state["player_blob"] = p_blob
                    cap_state["is_center"] = is_center
                    cap_state["seq"] = seq
                cap_event.set()

    def inference_worker():
        last_seq = -1
        locked_key = None
        recoil_acc = 0.0
        last_recoil_t = time.perf_counter()
        while state["running"]:
            cap_event.wait(timeout=0.05)
            cap_event.clear()

            with cap_lock:
                seq = cap_state["seq"]
                if seq == last_seq or cap_state["player_blob"] is None:
                    continue
                p_blob = cap_state["player_blob"]
                is_center = cap_state["is_center"]
                last_seq = seq

            t0 = time.perf_counter()
            off_x = crop_left if is_center else 0
            off_y = crop_top if is_center else 0

            if is_center:
                players_raw = run_from_blob(
                    p640_sess, p640_inp, p_blob, prep_640, PLAYER_CONF, offset_x=off_x, offset_y=off_y
                )
            else:
                s960, i960 = get_p960()
                players_raw = run_from_blob(
                    s960, i960, p_blob, prep_960, PLAYER_CONF, offset_x=0, offset_y=0
                )

            players_filtered = [
                p for p in players_raw if not is_own_player(p[0], p[1], p[2], p[3], scr_w, scr_h)
            ]
            players_smooth = player_smoother.update(players_filtered)

            rmb_held = bool(ctypes.windll.user32.GetAsyncKeyState(AIM_VK) & 0x8000)

            if state["aim_enabled"] and rmb_held:
                targets = [
                    (tid, (x1 + x2) / 2.0, y1 + (y2 - y1) * HEAD_Y_RATIO, missed)
                    for tid, (x1, y1, x2, y2, conf, _), missed in players_smooth
                ]

                chosen = None
                if locked_key is not None:
                    for tid, tx, ty, missed in targets:
                        if tid == locked_key:
                            chosen = (tid, tx, ty, missed)
                            break
                if chosen is None and targets:
                    best_dist = AIM_FOV_PX
                    for tid, tx, ty, missed in targets:
                        d = math.hypot(tx - center_x, ty - center_y)
                        if d < best_dist:
                            best_dist = d
                            chosen = (tid, tx, ty, missed)

                if chosen is not None:
                    locked_key = chosen[0]
                    err_x = chosen[1] - center_x
                    err_y = chosen[2] - center_y
                    dx = 0.0 if abs(err_x) < AIM_X_DEADZONE else err_x * AIM_SMOOTH_X
                    dy = 0.0 if abs(err_y) < AIM_Y_DEADZONE else err_y * AIM_SMOOTH_Y
                    if abs(dx) >= 1.0 or abs(dy) >= 1.0:
                        dx = max(-AIM_MAX_STEP, min(AIM_MAX_STEP, dx))
                        dy = max(-AIM_MAX_STEP, min(AIM_MAX_STEP, dy))
                        move_mouse_rel(dx, dy)
            else:
                locked_key = None

            now_r = time.perf_counter()
            dt_r = now_r - last_recoil_t
            last_recoil_t = now_r
            lmb_held = bool(ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            if state["aim_enabled"] and RECOIL_ENABLED and lmb_held:
                recoil_acc += RECOIL_PX_PER_SEC * dt_r
                step_y = int(recoil_acc)
                if step_y >= 1:
                    move_mouse_rel(0, step_y)
                    recoil_acc -= step_y
            else:
                recoil_acc = 0.0

            # Request the next fresh frame AFTER mouse movement so capture is always post-move & 0ms stale!
            req_event.set()

            dt = time.perf_counter() - t0
            fps = 1.0 / dt if dt > 0 else 0.0
            with lock:
                state["players"] = [box for _, box, _ in players_smooth]
                state["fps"] = fps
                state["draw_seq"] += 1

    threading.Thread(target=config_watcher, daemon=True).start()
    threading.Thread(target=capture_worker, daemon=True).start()
    threading.Thread(target=inference_worker, daemon=True).start()

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{scr_w}x{scr_h}+{scr_x}+{scr_y}")
    root.configure(bg=TRANSPARENT_BG)
    root.wm_attributes("-topmost", True)
    root.wm_attributes("-transparentcolor", TRANSPARENT_BG)

    canvas = tk.Canvas(root, width=scr_w, height=scr_h, bg=TRANSPARENT_BG, highlightthickness=0)
    canvas.pack(fill="both", expand=True)

    root.update()
    GA_ROOT = 2
    hwnd = ctypes.windll.user32.GetAncestor(root.winfo_id(), GA_ROOT) or root.winfo_id()
    make_clickthrough(hwnd)

    def hotkey_watcher():
        f6_was_down = False
        f7_was_down = False
        while state["running"]:
            if (
                (ctypes.windll.user32.GetAsyncKeyState(VK_F8) & 0x8001)
                or (ctypes.windll.user32.GetAsyncKeyState(VK_F9) & 0x8001)
                or (ctypes.windll.user32.GetAsyncKeyState(VK_END) & 0x8001)
            ):
                state["running"] = False
                os._exit(0)

            f6_down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_F6) & 0x8000)
            if f6_down and not f6_was_down:
                state["center_mode"] = not state["center_mode"]
            f6_was_down = f6_down

            f7_down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_F7) & 0x8000)
            if f7_down and not f7_was_down:
                state["aim_enabled"] = not state["aim_enabled"]
            f7_was_down = f7_down
            time.sleep(0.03)

    threading.Thread(target=hotkey_watcher, daemon=True).start()

    last_drawn_seq = -1

    def draw_loop():
        nonlocal last_drawn_seq
        with lock:
            cur_seq = state["draw_seq"]
            if cur_seq == last_drawn_seq:
                root.after(2, draw_loop)
                return
            last_drawn_seq = cur_seq
            players = list(state["players"])
            fps = state["fps"]
        aim_on = state["aim_enabled"]
        is_center = state["center_mode"]

        canvas.delete("all")

        if SHOW_HUD:
            hud_w = 590
            hud_h = 34
            hx1 = scr_w // 2 - hud_w // 2
            hy1 = 12
            hx2 = hx1 + hud_w
            hy2 = hy1 + hud_h
            canvas.create_rectangle(hx1, hy1, hx2, hy2, fill="#0D131A", outline="#1E2D3D", width=1)
            canvas.create_rectangle(hx1, hy1, hx1 + 4, hy2, fill=ESP_COLOR, outline="")

            mode_txt = "CENTER 640" if is_center else "FULL 960"
            aim_txt = "AIM ON" if aim_on else "AIM OFF"
            aim_col = "#00FF88" if aim_on else "#FF5555"

            canvas.create_text(
                hx1 + 16, hy1 + hud_h // 2,
                text="AI v7", anchor="w", fill=ESP_COLOR, font=("Segoe UI", 10, "bold"),
            )
            canvas.create_text(
                hx1 + 70, hy1 + hud_h // 2,
                text=f"{mode_txt} [F6]   |   {fps:.0f} FPS   |   METE: {len(players)}",
                anchor="w", fill="#E2E8F0", font=("Consolas", 10, "bold"),
            )
            canvas.create_text(
                hx2 - 108, hy1 + hud_h // 2,
                text=f"{aim_txt} [F7]", anchor="e", fill=aim_col, font=("Consolas", 10, "bold"),
            )
            canvas.create_text(
                hx2 - 14, hy1 + hud_h // 2,
                text="EXIT [F8]", anchor="e", fill="#94A3B8", font=("Consolas", 9, "bold"),
            )

        if is_center and SHOW_HUD:
            canvas.create_rectangle(
                crop_left, crop_top, crop_left + crop_w, crop_top + crop_h,
                outline="#23374D", width=1, dash=(6, 6),
            )

        if aim_on and SHOW_FOV:
            canvas.create_oval(
                center_x - AIM_FOV_PX,
                center_y - AIM_FOV_PX,
                center_x + AIM_FOV_PX,
                center_y + AIM_FOV_PX,
                outline=FOV_COLOR,
                width=1,
                dash=(4, 5),
            )

        for x1, y1, x2, y2, conf, _ in players:
            draw_corner_box(canvas, x1, y1, x2, y2, box_color=ESP_COLOR, corner_color="#FFFFFF")
            hx = int((x1 + x2) / 2.0)
            hy = int(y1 + (y2 - y1) * HEAD_Y_RATIO)
            if SHOW_SNAPLINES:
                canvas.create_line(center_x, scr_h - 40, hx, int(y2), fill=ESP_COLOR, width=1, dash=(4, 4))
            if SHOW_HEAD_DOT:
                canvas.create_oval(hx - 5, hy - 5, hx + 5, hy + 5, fill=HEAD_DOT_COLOR, outline="#FFFFFF", width=1)
            if SHOW_LABELS:
                lbl = f"player {int(conf * 100)}%"
                lw = len(lbl) * 7 + 10
                ly2 = max(18, int(y1) - 4)
                ly1 = ly2 - 16
                canvas.create_rectangle(hx - lw // 2, ly1, hx + lw // 2, ly2, fill="#0D131A", outline=ESP_COLOR, width=1)
                canvas.create_text(
                    hx,
                    (ly1 + ly2) // 2,
                    text=lbl,
                    anchor="center",
                    fill="#E2E8F0",
                    font=("Consolas", 9, "bold"),
                )

        root.after(2, draw_loop)

    root.after(8, draw_loop)
    root.mainloop()
    state["running"] = False


if __name__ == "__main__":
    main()
