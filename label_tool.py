import glob
import os
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk

IMG_DIR = r"C:\Users\mbari\Videos\Captures\dataset_raw\images"
LBL_DIR = r"C:\Users\mbari\Videos\Captures\dataset_v3\raw_labels"

CLASSES = {
    0: ("player", "#00ff66"),
    1: ("police", "#3399ff"),
}

os.makedirs(LBL_DIR, exist_ok=True)
with open(os.path.join(LBL_DIR, "classes.txt"), "w", encoding="utf-8") as f:
    f.write("player\npolice\n")


class YoloLabeler:
    def __init__(self, root):
        self.root = root
        self.root.title("Brzi YOLO Labeler (v5: Player + Police)")
        self.root.state("zoomed")
        self.root.configure(bg="#1e1e1e")

        self.images = sorted(glob.glob(os.path.join(IMG_DIR, "*.jpg")))
        if not self.images:
            messagebox.showerror("Greska", f"Nema slika u {IMG_DIR}")
            root.destroy()
            return

        self.idx = 0
        self.active_cls = 0
        self.boxes = []  # list of (cls_id, x1_n, y1_n, x2_n, y2_n)
        self.history = []
        self.drag_start = None
        self.drag_rect = None
        self.disp_w = 1
        self.disp_h = 1
        self.off_x = 0
        self.off_y = 0
        self.tk_img = None

        bar = tk.Frame(root, bg="#252526", pady=6)
        bar.pack(fill="x")

        self.info_lbl = tk.Label(
            bar,
            text="",
            fg="#00ff88",
            bg="#252526",
            font=("Consolas", 11, "bold"),
        )
        self.info_lbl.pack(side="left", padx=12)

        btn_style = {"bg": "#3c3c3c", "fg": "#ffffff", "relief": "flat", "padx": 10, "pady": 4, "font": ("Segoe UI", 9, "bold")}
        tk.Button(bar, text="< Prethodna (A)", command=self.prev_img, **btn_style).pack(side="right", padx=4)
        tk.Button(bar, text="Sljedeca (D) >", command=self.next_img, **btn_style).pack(side="right", padx=4)
        tk.Button(bar, text="Sljedeca s okvirom (F)", command=self.next_labeled, **btn_style).pack(side="right", padx=4)
        tk.Button(bar, text="Ocisti sve (C)", command=self.clear_boxes, **btn_style).pack(side="right", padx=4)
        tk.Button(bar, text="Undo (Z)", command=self.undo, **btn_style).pack(side="right", padx=4)

        self.btn_cls1 = tk.Button(bar, text="1: Player", command=lambda: self.set_cls(0), **btn_style)
        self.btn_cls1.pack(side="right", padx=4)
        self.btn_cls2 = tk.Button(bar, text="2: Police", command=lambda: self.set_cls(1), **btn_style)
        self.btn_cls2.pack(side="right", padx=4)

        help_lbl = tk.Label(
            root,
            text="Lijevi klik+povuci = Nacrtaj | Desni klik = Obrisi | Srednji klik (ili Shift+Lijevi) na okvir = Prebaci Player<->Police | 1/2 = Klasa | A/D = Nazad/Naprijed | F = Sljedeca s okvirom",
            fg="#cccccc",
            bg="#1e1e1e",
            font=("Segoe UI", 9),
        )
        help_lbl.pack(fill="x", pady=2)

        self.canvas = tk.Canvas(root, bg="#111111", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)

        self.canvas.bind("<ButtonPress-1>", self.on_left_down)
        self.canvas.bind("<Shift-ButtonPress-1>", self.on_toggle_class_click)
        self.canvas.bind("<ButtonPress-2>", self.on_toggle_class_click)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_up)
        self.canvas.bind("<ButtonPress-3>", self.on_right_click)
        self.canvas.bind("<Configure>", lambda e: self.render())

        root.bind("<KeyPress-1>", lambda e: self.set_cls(0))
        root.bind("<KeyPress-2>", lambda e: self.set_cls(1))
        root.bind("<KeyPress-a>", lambda e: self.prev_img())
        root.bind("<KeyPress-A>", lambda e: self.prev_img())
        root.bind("<Left>", lambda e: self.prev_img())
        root.bind("<KeyPress-d>", lambda e: self.next_img())
        root.bind("<KeyPress-D>", lambda e: self.next_img())
        root.bind("<Right>", lambda e: self.next_img())
        root.bind("<KeyPress-f>", lambda e: self.next_labeled())
        root.bind("<KeyPress-F>", lambda e: self.next_labeled())
        root.bind("<KeyPress-z>", lambda e: self.undo())
        root.bind("<KeyPress-Z>", lambda e: self.undo())
        root.bind("<KeyPress-c>", lambda e: self.clear_boxes())
        root.bind("<KeyPress-C>", lambda e: self.clear_boxes())
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.update_cls_buttons()
        self.load_image()

    def set_cls(self, cls_id):
        self.active_cls = cls_id
        self.update_cls_buttons()
        self.render()

    def update_cls_buttons(self):
        self.btn_cls1.config(bg="#00aa55" if self.active_cls == 0 else "#3c3c3c")
        self.btn_cls2.config(bg="#2277cc" if self.active_cls == 1 else "#3c3c3c")

    def label_path_for(self, img_path):
        stem = os.path.splitext(os.path.basename(img_path))[0]
        return os.path.join(LBL_DIR, stem + ".txt")

    def load_image(self):
        img_path = self.images[self.idx]
        self.pil_orig = Image.open(img_path)
        self.boxes = []
        self.history = []

        lbl_p = self.label_path_for(img_path)
        if os.path.exists(lbl_p):
            with open(lbl_p, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        cls_id = int(float(parts[0]))
                        xc, yc, w, h = map(float, parts[1:])
                        self.boxes.append((
                            cls_id,
                            max(0.0, xc - w / 2.0),
                            max(0.0, yc - h / 2.0),
                            min(1.0, xc + w / 2.0),
                            min(1.0, yc + h / 2.0),
                        ))
        self.render()

    def save_labels(self):
        img_path = self.images[self.idx]
        lbl_p = self.label_path_for(img_path)
        lines = []
        for cls_id, x1, y1, x2, y2 in self.boxes:
            xc = (x1 + x2) / 2.0
            yc = (y1 + y2) / 2.0
            w = max(0.002, x2 - x1)
            h = max(0.002, y2 - y1)
            lines.append(f"{cls_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}")
        with open(lbl_p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def render(self):
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        iw, ih = self.pil_orig.size
        scale = min(cw / iw, ch / ih)
        self.disp_w = max(1, int(iw * scale))
        self.disp_h = max(1, int(ih * scale))
        self.off_x = (cw - self.disp_w) // 2
        self.off_y = (ch - self.disp_h) // 2

        resized = self.pil_orig.resize((self.disp_w, self.disp_h), Image.Resampling.BILINEAR)
        self.tk_img = ImageTk.PhotoImage(resized)

        self.canvas.delete("all")
        self.canvas.create_image(self.off_x, self.off_y, anchor="nw", image=self.tk_img)

        for cls_id, x1, y1, x2, y2 in self.boxes:
            cls_name, color = CLASSES.get(cls_id, ("player", "#00ff66"))
            sx1 = self.off_x + x1 * self.disp_w
            sy1 = self.off_y + y1 * self.disp_h
            sx2 = self.off_x + x2 * self.disp_w
            sy2 = self.off_y + y2 * self.disp_h
            self.canvas.create_rectangle(sx1, sy1, sx2, sy2, outline=color, width=2)
            self.canvas.create_text(sx1 + 2, max(10, sy1 - 9), text=cls_name, anchor="w", fill=color, font=("Consolas", 9, "bold"))

        name = os.path.basename(self.images[self.idx])
        act_name, _ = CLASSES[self.active_cls]
        self.info_lbl.config(
            text=f"Slika {self.idx + 1}/{len(self.images)} ({name}) | Okvira: {len(self.boxes)} | Klasa: {act_name}"
        )

    def push_history(self):
        self.history.append(list(self.boxes))

    def on_left_down(self, event):
        if event.state & 0x0001:  # Shift held -> handled by Shift-ButtonPress-1
            return
        self.drag_start = (event.x, event.y)
        _, color = CLASSES[self.active_cls]
        self.drag_rect = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline=color, width=2, dash=(4, 2)
        )

    def on_left_drag(self, event):
        if self.drag_start and self.drag_rect:
            self.canvas.coords(self.drag_rect, self.drag_start[0], self.drag_start[1], event.x, event.y)

    def on_left_up(self, event):
        if not self.drag_start:
            return
        x0, y0 = self.drag_start
        x1, y1 = event.x, event.y
        self.drag_start = None
        if self.drag_rect:
            self.canvas.delete(self.drag_rect)
            self.drag_rect = None

        if abs(x1 - x0) < 6 or abs(y1 - y0) < 6:
            return

        nx1 = min(max((min(x0, x1) - self.off_x) / self.disp_w, 0.0), 1.0)
        ny1 = min(max((min(y0, y1) - self.off_y) / self.disp_h, 0.0), 1.0)
        nx2 = min(max((max(x0, x1) - self.off_x) / self.disp_w, 0.0), 1.0)
        ny2 = min(max((max(y0, y1) - self.off_y) / self.disp_h, 0.0), 1.0)

        if nx2 - nx1 < 0.005 or ny2 - ny1 < 0.005:
            return

        self.push_history()
        self.boxes.append((self.active_cls, nx1, ny1, nx2, ny2))
        self.save_labels()
        self.render()

    def _find_box_at(self, event):
        nx = (event.x - self.off_x) / self.disp_w
        ny = (event.y - self.off_y) / self.disp_h
        candidates = [
            (i, (x2 - x1) * (y2 - y1))
            for i, (_, x1, y1, x2, y2) in enumerate(self.boxes)
            if x1 <= nx <= x2 and y1 <= ny <= y2
        ]
        return min(candidates, key=lambda c: c[1])[0] if candidates else None

    def on_right_click(self, event):
        target_idx = self._find_box_at(event)
        if target_idx is not None:
            self.push_history()
            self.boxes.pop(target_idx)
            self.save_labels()
            self.render()

    def on_toggle_class_click(self, event):
        target_idx = self._find_box_at(event)
        if target_idx is not None:
            self.push_history()
            cls_id, x1, y1, x2, y2 = self.boxes[target_idx]
            new_cls = 1 if cls_id == 0 else 0
            self.boxes[target_idx] = (new_cls, x1, y1, x2, y2)
            self.save_labels()
            self.render()

    def undo(self):
        if self.history:
            self.boxes = self.history.pop()
            self.save_labels()
            self.render()

    def clear_boxes(self):
        if self.boxes:
            self.push_history()
            self.boxes = []
            self.save_labels()
            self.render()

    def prev_img(self):
        self.save_labels()
        if self.idx > 0:
            self.idx -= 1
            self.load_image()

    def next_img(self):
        self.save_labels()
        if self.idx < len(self.images) - 1:
            self.idx += 1
            self.load_image()

    def next_labeled(self):
        self.save_labels()
        for j in range(self.idx + 1, len(self.images)):
            p = self.label_path_for(self.images[j])
            if os.path.exists(p) and os.path.getsize(p) > 0:
                self.idx = j
                self.load_image()
                return

    def on_close(self):
        self.save_labels()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    YoloLabeler(root)
    root.mainloop()
