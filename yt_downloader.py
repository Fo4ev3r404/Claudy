import os
import re
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
import yt_dlp

OUT_DIR = r"C:\Users\mbari\Videos\Captures\novi_klipovi"
ARCHIVE_FILE = os.path.join(OUT_DIR, "downloaded.txt")
os.makedirs(OUT_DIR, exist_ok=True)


class YtDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Montage Downloader -> novi_klipovi")
        self.root.geometry("780x620")
        self.root.configure(bg="#11161D")
        self.downloading = False
        self.searching = False

        header = tk.Frame(root, bg="#11161D", pady=10, padx=14)
        header.pack(fill="x")
        tk.Label(
            header,
            text="YouTube Montage Downloader (za AI dataset)",
            font=("Segoe UI", 13, "bold"),
            fg="#00FF88",
            bg="#11161D",
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f"Sprema u: {OUT_DIR}",
            font=("Consolas", 9),
            fg="#94A3B8",
            bg="#11161D",
        ).pack(anchor="w", pady=(2, 0))

        body = tk.Frame(root, bg="#11161D", padx=14)
        body.pack(fill="both", expand=True)

        search_frame = tk.Frame(body, bg="#11161D", pady=4)
        search_frame.pack(fill="x")
        tk.Label(
            search_frame,
            text="Pretraži YouTube:",
            font=("Segoe UI", 10, "bold"),
            fg="#38BDF8",
            bg="#11161D",
        ).pack(side="left")

        self.search_var = tk.StringVar(value="rob run pvp montage")
        self.search_entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            font=("Consolas", 10),
            bg="#1A222D",
            fg="#F8FAFC",
            insertbackground="#38BDF8",
            relief="flat",
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(8, 8), ipady=4)

        self.search_btn = tk.Button(
            search_frame,
            text="Traži i dodaj (25)",
            command=self.start_search,
            font=("Segoe UI", 9, "bold"),
            bg="#0284C7",
            fg="#FFFFFF",
            activebackground="#38BDF8",
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.search_btn.pack(side="right")

        tk.Label(
            body,
            text="YouTube linkovi za skidanje (svaki link u novi red, podržava i playliste):",
            font=("Segoe UI", 10),
            fg="#E2E8F0",
            bg="#11161D",
        ).pack(anchor="w", pady=(6, 4))

        self.url_box = scrolledtext.ScrolledText(
            body,
            height=7,
            font=("Consolas", 10),
            bg="#1A222D",
            fg="#F8FAFC",
            insertbackground="#00FF88",
            relief="flat",
            padx=8,
            pady=8,
        )
        self.url_box.pack(fill="x")

        opts_frame = tk.Frame(body, bg="#11161D", pady=10)
        opts_frame.pack(fill="x")

        self.video_only_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            opts_frame,
            text="1080p bez zvuka (najbolja kvaliteta i najbrže za AI, bez ffmpeg)",
            variable=self.video_only_var,
            font=("Segoe UI", 9),
            fg="#E2E8F0",
            bg="#11161D",
            selectcolor="#1A222D",
            activebackground="#11161D",
            activeforeground="#00FF88",
        ).pack(side="left")

        btn_frame = tk.Frame(body, bg="#11161D")
        btn_frame.pack(fill="x", pady=(0, 8))

        self.dl_btn = tk.Button(
            btn_frame,
            text="Skini videe",
            command=self.start_download,
            font=("Segoe UI", 10, "bold"),
            bg="#00CC6A",
            fg="#0B1117",
            activebackground="#00FF88",
            relief="flat",
            padx=18,
            pady=6,
            cursor="hand2",
        )
        self.dl_btn.pack(side="left")

        tk.Button(
            btn_frame,
            text="Otvori folder",
            command=lambda: os.startfile(OUT_DIR),
            font=("Segoe UI", 10),
            bg="#1F2937",
            fg="#E2E8F0",
            activebackground="#374151",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            btn_frame,
            text="Očisti listu",
            command=lambda: self.url_box.delete("1.0", "end"),
            font=("Segoe UI", 10),
            bg="#1F2937",
            fg="#94A3B8",
            activebackground="#374151",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
        ).pack(side="right")

        self.progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(4, 8))

        self.log_box = scrolledtext.ScrolledText(
            body,
            height=11,
            font=("Consolas", 9),
            bg="#0B1016",
            fg="#CBD5E1",
            relief="flat",
            padx=8,
            pady=8,
            state="disabled",
        )
        self.log_box.pack(fill="both", expand=True, pady=(0, 12))

    def log(self, msg):
        def _append():
            self.log_box.configure(state="normal")
            self.log_box.insert("end", msg + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        self.root.after(0, _append)

    def set_progress(self, pct):
        self.root.after(0, lambda: self.progress.configure(value=pct))

    def start_search(self):
        if self.searching or self.downloading:
            return
        query = self.search_var.get().strip()
        if not query:
            messagebox.showwarning("Prazna pretraga", "Upiši pojam za pretragu (npr. rob run pvp montage).")
            return
        self.searching = True
        self.search_btn.configure(state="disabled", text="Tražim...")
        threading.Thread(target=self._search_worker, args=(query,), daemon=True).start()

    def _get_existing_ids(self):
        seen_ids = set()
        if os.path.exists(ARCHIVE_FILE):
            with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        seen_ids.add(parts[1])
        # Also scan filenames in novi_klipovi for [youtube_id] and sync into downloaded.txt
        added_to_archive = []
        for fname in os.listdir(OUT_DIR):
            m = re.search(r"\[([A-Za-z0-9_-]{11})\]\.\w+$", fname)
            if m:
                vid = m.group(1)
                if vid not in seen_ids:
                    seen_ids.add(vid)
                    added_to_archive.append(f"youtube {vid}\n")
        if added_to_archive:
            with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
                f.writelines(added_to_archive)
        return seen_ids

    @staticmethod
    def _extract_yt_id(url):
        m = re.search(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})", url)
        return m.group(1) if m else None

    def _search_worker(self, query):
        seen_ids = self._get_existing_ids()

        existing_urls = self.url_box.get("1.0", "end")
        must_words = ("rob run", "robrun", "looty bay")
        skip_words = (
            "cheat", "esp", "aimbot", "hack", "script", "settings",
            "roblox", "blox", "obby", "minecraft", "fortnite", "gta", "fivem", "unturned",
        )
        self.log(f"Tražim na YouTubeu: '{query}' ...")
        added = 0
        try:
            ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                res = ydl.extract_info(f"ytsearch25:{query}", download=False)
                for entry in (res.get("entries") or []):
                    vid = entry.get("id")
                    title = entry.get("title") or ""
                    dur = entry.get("duration") or 0
                    if not vid or vid in seen_ids or vid in existing_urls:
                        continue
                    tl = title.lower()
                    if not any(m in tl for m in must_words):
                        continue
                    if any(w in tl for w in skip_words):
                        continue
                    if 20 <= dur <= 1200:
                        url = f"https://www.youtube.com/watch?v={vid}"
                        self.root.after(0, lambda u=url: self.url_box.insert("end", u + "\n"))
                        self.log(f"  + [{int(dur)}s] {title}")
                        added += 1
            self.log(f"Dodano {added} novih videa u listu (preskočeni već skinuti i cheat/settings videi).")
        except Exception as e:
            self.log(f"[GRESKA pretrage] {e}")
        finally:
            self.searching = False
            self.root.after(0, lambda: self.search_btn.configure(state="normal", text="Traži i dodaj (25)"))

    def start_download(self):
        if self.downloading:
            return
        raw = self.url_box.get("1.0", "end").strip()
        urls = [u.strip() for u in re.split(r"[\r\n\s]+", raw) if u.strip().startswith("http")]
        if not urls:
            messagebox.showwarning("Nema linkova", "Zalijepi barem jedan YouTube link (https://...).")
            return

        self.downloading = True
        self.dl_btn.configure(state="disabled", text="Skidanje u tijeku...")
        self.set_progress(0)
        threading.Thread(target=self._worker, args=(urls,), daemon=True).start()

    def _worker(self, urls):
        fmt = (
            "bestvideo[ext=mp4][vcodec^=avc1][height<=1080]/bestvideo[ext=mp4][height<=1080]/best[ext=mp4][height<=1080]/best[ext=mp4]/best"
            if self.video_only_var.get()
            else "best[ext=mp4][height<=1080]/best[ext=mp4]/best"
        )

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                if total > 0:
                    self.set_progress(min(100.0, done * 100.0 / total))
            elif d["status"] == "finished":
                self.set_progress(100.0)
                fname = os.path.basename(d.get("filename", ""))
                self.log(f"[OK] Skinuto: {fname}")

        ydl_opts = {
            "format": fmt,
            "outtmpl": os.path.join(OUT_DIR, "%(title).80s [%(id)s].%(ext)s"),
            "download_archive": ARCHIVE_FILE,
            "ignoreerrors": True,
            "noplaylist": False,
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
        }

        self.log(f"Pokrecem skidanje ({len(urls)} linkova)...")
        seen_ids = self._get_existing_ids()
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                for i, url in enumerate(urls, 1):
                    vid = self._extract_yt_id(url)
                    if vid and vid in seen_ids:
                        self.log(f"-> [{i}/{len(urls)}] PRESKOČENO (već skinuto): {url}")
                        continue
                    self.log(f"-> [{i}/{len(urls)}] {url}")
                    ydl.download([url])
                    if vid:
                        seen_ids.add(vid)
            self.log("=== Gotovo! Svi videi su u novi_klipovi. ===")
        except Exception as e:
            self.log(f"[GRESKA] {e}")
        finally:
            self.downloading = False
            self.root.after(0, lambda: self.dl_btn.configure(state="normal", text="Skini videe"))


if __name__ == "__main__":
    root = tk.Tk()
    app = YtDownloaderApp(root)
    root.mainloop()
