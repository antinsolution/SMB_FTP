"""
ScanServer - FTP & SMB server nhỏ gọn cho máy scan
Yêu cầu: pip install pyftpdlib impacket pystray Pillow
"""

import os
import sys
import json
import socket
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import logging

# ── FTP ──────────────────────────────────────────────────────────────────────
try:
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    from pyftpdlib.authorizers import DummyAuthorizer
    HAS_FTP = True
except ImportError:
    HAS_FTP = False

# ── SMB ──────────────────────────────────────────────────────────────────────
try:
    from impacket.smbserver import SimpleSMBServer
    HAS_SMB = True
except ImportError:
    HAS_SMB = False

# ── Tray ─────────────────────────────────────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


# ─────────────────────────────────────────────────────────────────────────────
#  Server threads
# ─────────────────────────────────────────────────────────────────────────────

class FTPThread(threading.Thread):
    def __init__(self, host, port, scan_dir, user, password):
        super().__init__(daemon=True)
        self.host, self.port = host, port
        self.scan_dir, self.user, self.password = scan_dir, user, password
        self.server = None

    def run(self):
        os.makedirs(self.scan_dir, exist_ok=True)
        auth = DummyAuthorizer()
        auth.add_user(self.user, self.password, self.scan_dir, perm="elradfmw")

        handler = FTPHandler
        handler.authorizer = auth
        handler.passive_ports = range(60000, 60100)
        handler.banner = "ScanServer FTP ready."

        self.server = FTPServer((self.host, self.port), handler)
        self.server.serve_forever()

    def stop(self):
        if self.server:
            self.server.close_all()


class SMBThread(threading.Thread):
    def __init__(self, host, port, scan_dir, share_name):
        super().__init__(daemon=True)
        self.host, self.port = host, port
        self.scan_dir, self.share_name = scan_dir, share_name
        self.server = None

    def run(self):
        os.makedirs(self.scan_dir, exist_ok=True)
        self.server = SimpleSMBServer(listenAddress=self.host, listenPort=self.port)
        self.server.addShare(self.share_name.upper(), self.scan_dir, "Scan Share")
        self.server.setSMBChallenge("")
        self.server.setLogFile(os.devnull)
        self.server.start()

    def stop(self):
        if self.server:
            try:
                self.server.stop()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  Tray icon
# ─────────────────────────────────────────────────────────────────────────────

def make_tray_icon():
    """Vẽ icon tray đơn giản bằng Pillow."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Nền tròn xanh
    d.ellipse([4, 4, size - 4, size - 4], fill="#2563EB")
    # Chữ S trắng
    d.rectangle([20, 18, 44, 30], fill="white")
    d.rectangle([20, 34, 44, 46], fill="white")
    d.rectangle([20, 18, 32, 46], fill="white")
    return img


# ─────────────────────────────────────────────────────────────────────────────
#  Config path
# ─────────────────────────────────────────────────────────────────────────────

# ── Khi chạy từ PyInstaller exe, __file__ không còn đúng nữa ────────────────
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULT_CONFIG = {
    "scan_dir": os.path.expanduser("~/Scans"),
    "ftp_port": 2121,
    "ftp_user": "scanner",
    "ftp_pass": "1234",
    "ftp_enabled": False,
    "smb_port": 1445,
    "smb_share": "SCANS",
    "smb_enabled": False,
}


def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
        # Merge with defaults so new keys are filled in
        merged = DEFAULT_CONFIG.copy()
        merged.update(cfg)
        # Migrate old ftp_dir/smb_dir to scan_dir
        if "scan_dir" not in cfg:
            old_dir = cfg.get("ftp_dir") or cfg.get("smb_dir") or os.path.expanduser("~/Scans")
            merged["scan_dir"] = old_dir
        # Expand ~ trong đường dẫn
        val = merged.get("scan_dir", "")
        if val.startswith("~"):
            merged["scan_dir"] = os.path.expanduser(val)
        return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()


def save_config(data):
    try:
        data = dict(data)
        # Resolve path to portable form before saving
        val = data.get("scan_dir", "")
        if val.startswith(os.path.expanduser("~")):
            data["scan_dir"] = val.replace(os.path.expanduser("~"), "~")
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass  # silently ignore write errors


def get_local_ip():
    """Lấy địa chỉ IP local (không phải loopback)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.5)
        # Không cần kết nối thật, chỉ để lấy ra IP
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"


# ─────────────────────────────────────────────────────────────────────────────
#  Main GUI
# ─────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ScanServer")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._ftp_thread: FTPThread | None = None
        self._smb_thread: SMBThread | None = None
        self._tray = None

        # Load cấu hình đã lưu
        self._config = load_config()

        self._build_ui()
        self._check_deps()

        # Auto-start servers nếu lần trước đang bật
        self.after(100, self._auto_start)

        # Thu nhỏ xuống khay hệ thống sau khi khởi động
        self.after(300, self._start_minimized)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        main = ttk.Frame(self, padding=10)
        main.pack(fill="both", expand=True)

        # ── Header ─────────────────────────────────────────────────────────────
        hdr = ttk.Frame(main)
        hdr.pack(fill="x", pady=(0, 10))
        ttk.Label(hdr, text="📡 ScanServer", font=("", 14, "bold"),
                  foreground="#2563EB").pack(side="left")
        local_ip = get_local_ip()
        ttk.Label(hdr, text=f"🌐 {local_ip}", font=("", 9),
                  foreground="#555").pack(side="right")

        # ── Shared directory ───────────────────────────────────────────────────
        dir_frame = ttk.LabelFrame(main, text="📁 Thư mục chung", padding=6)
        dir_frame.pack(fill="x", pady=(0, 8))

        self._scan_dir = tk.StringVar(value=self._config.get("scan_dir", os.path.expanduser("~/Scans")))
        ed = ttk.Entry(dir_frame, textvariable=self._scan_dir, width=45)
        ed.pack(side="left", padx=(0, 4), fill="x", expand=True)
        ttk.Button(dir_frame, text="…", width=3,
                   command=lambda: self._browse(self._scan_dir)).pack(side="left")

        # ── Server cards side-by-side ──────────────────────────────────────────
        cards = ttk.Frame(main)
        cards.pack(fill="both", expand=True, pady=(0, 8))

        # -- FTP card --
        ftp_card = ttk.LabelFrame(cards, text="🔵 FTP Server", padding=10)
        ftp_card.pack(side="left", fill="both", expand=True, padx=(0, 5))

        gf = ttk.Frame(ftp_card)
        gf.pack(fill="x", pady=(0, 6))
        ttk.Label(gf, text="Port:", width=6, anchor="e").grid(row=0, column=0, padx=(0, 4), pady=2, sticky="e")
        self._ftp_port = tk.IntVar(value=self._config.get("ftp_port", 2121))
        ttk.Spinbox(gf, from_=1, to=65535, textvariable=self._ftp_port,
                    width=8).grid(row=0, column=1, padx=(0, 10), pady=2, sticky="w")

        ttk.Label(gf, text="User:", width=6, anchor="e").grid(row=1, column=0, padx=(0, 4), pady=2, sticky="e")
        self._ftp_user = tk.StringVar(value=self._config.get("ftp_user", "scanner"))
        ttk.Entry(gf, textvariable=self._ftp_user, width=14).grid(row=1, column=1, padx=(0, 10), pady=2, sticky="w")

        ttk.Label(gf, text="Pass:", width=6, anchor="e").grid(row=2, column=0, padx=(0, 4), pady=2, sticky="e")
        self._ftp_pass = tk.StringVar(value=self._config.get("ftp_pass", "1234"))
        ttk.Entry(gf, textvariable=self._ftp_pass, show="*", width=14).grid(row=2, column=1, padx=(0, 10), pady=2, sticky="w")

        ftp_btns = ttk.Frame(ftp_card)
        ftp_btns.pack(fill="x", pady=(4, 0))
        self._ftp_status = tk.StringVar(value="⚪")
        ttk.Label(ftp_btns, textvariable=self._ftp_status,
                  font=("", 10)).pack(side="left", padx=(0, 6))
        self._ftp_btn = ttk.Button(ftp_btns, text="▶ FTP",
                                   command=self._toggle_ftp)
        self._ftp_btn.pack(side="left")

        # -- SMB card --
        smb_card = ttk.LabelFrame(cards, text="🟠 SMB Server", padding=10)
        smb_card.pack(side="right", fill="both", expand=True, padx=(5, 0))

        gs = ttk.Frame(smb_card)
        gs.pack(fill="x", pady=(0, 6))
        ttk.Label(gs, text="Port:", width=6, anchor="e").grid(row=0, column=0, padx=(0, 4), pady=2, sticky="e")
        self._smb_port = tk.IntVar(value=self._config.get("smb_port", 1445))
        ttk.Spinbox(gs, from_=1, to=65535, textvariable=self._smb_port,
                    width=8).grid(row=0, column=1, padx=(0, 10), pady=2, sticky="w")

        ttk.Label(gs, text="Share:", width=6, anchor="e").grid(row=1, column=0, padx=(0, 4), pady=2, sticky="e")
        self._smb_share = tk.StringVar(value=self._config.get("smb_share", "SCANS"))
        ttk.Entry(gs, textvariable=self._smb_share, width=14).grid(row=1, column=1, padx=(0, 10), pady=2, sticky="w")

        ttk.Label(gs, text="🔓 Guest mode",
                  foreground="orange", font=("", 8)).grid(row=2, column=0, columnspan=2, pady=2, sticky="w")

        smb_btns = ttk.Frame(smb_card)
        smb_btns.pack(fill="x", pady=(4, 0))
        self._smb_status = tk.StringVar(value="⚪")
        ttk.Label(smb_btns, textvariable=self._smb_status,
                  font=("", 10)).pack(side="left", padx=(0, 6))
        self._smb_btn = ttk.Button(smb_btns, text="▶ SMB",
                                   command=self._toggle_smb)
        self._smb_btn.pack(side="left")

        # ── Bottom bar ────────────────────────────────────────────────────────
        bar = ttk.Frame(main)
        bar.pack(fill="x", pady=(4, 0))

        ttk.Button(bar, text="🗕 Thu nhỏ",
                   command=self._hide_to_tray).pack(side="left")
        ttk.Button(bar, text="Thoát",
                   command=self._quit).pack(side="right")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _browse(self, var: tk.StringVar):
        d = filedialog.askdirectory(initialdir=var.get())
        if d:
            var.set(d)

    def _check_deps(self):
        missing = []
        if not HAS_FTP:
            missing.append("pyftpdlib  (FTP)")
        if not HAS_SMB:
            missing.append("impacket   (SMB)")
        if not HAS_TRAY:
            missing.append("pystray + Pillow  (Tray icon)")
        if missing:
            msg = "Thiếu thư viện, cài bằng pip:\n\n" + "\n".join(missing)
            messagebox.showwarning("Thiếu thư viện", msg)

    def _start_minimized(self):
        """Thu nhỏ xuống khay hệ thống ngay khi khởi động."""
        if HAS_TRAY:
            self._hide_to_tray()

    def _auto_start(self):
        """Tự động khởi động server nếu lần trước đang bật."""
        if self._config.get("ftp_enabled") and HAS_FTP:
            self._toggle_ftp()
        if self._config.get("smb_enabled") and HAS_SMB:
            self._toggle_smb()

    def _gather_config(self):
        """Thu thập các giá trị config hiện tại từ giao diện."""
        return {
            "scan_dir": self._scan_dir.get(),
            "ftp_port": self._ftp_port.get(),
            "ftp_user": self._ftp_user.get(),
            "ftp_pass": self._ftp_pass.get(),
            "ftp_enabled": (self._ftp_thread is not None and self._ftp_thread.is_alive()),
            "smb_port": self._smb_port.get(),
            "smb_share": self._smb_share.get(),
            "smb_enabled": (self._smb_thread is not None and self._smb_thread.is_alive()),
        }

    # ── FTP toggle ────────────────────────────────────────────────────────────

    def _toggle_ftp(self):
        if self._ftp_thread and self._ftp_thread.is_alive():
            self._ftp_thread.stop()
            self._ftp_thread = None
            self._ftp_status.set("⚪")
            self._ftp_btn.config(text="▶ FTP")
            save_config(self._gather_config())
        else:
            if not HAS_FTP:
                messagebox.showerror("Lỗi", "Chưa cài pyftpdlib.\npip install pyftpdlib")
                return
            try:
                self._ftp_thread = FTPThread(
                    host="0.0.0.0",
                    port=self._ftp_port.get(),
                    scan_dir=self._scan_dir.get(),
                    user=self._ftp_user.get(),
                    password=self._ftp_pass.get(),
                )
                self._ftp_thread.start()
                self._ftp_status.set("🟢")
                self._ftp_btn.config(text="⏹ FTP")
                save_config(self._gather_config())
            except Exception as e:
                messagebox.showerror("Lỗi FTP", str(e))

    # ── SMB toggle ────────────────────────────────────────────────────────────

    def _toggle_smb(self):
        if self._smb_thread and self._smb_thread.is_alive():
            self._smb_thread.stop()
            self._smb_thread = None
            self._smb_status.set("⚪")
            self._smb_btn.config(text="▶ SMB")
            save_config(self._gather_config())
        else:
            if not HAS_SMB:
                messagebox.showerror("Lỗi", "Chưa cài impacket.\npip install impacket")
                return
            try:
                self._smb_thread = SMBThread(
                    host="0.0.0.0",
                    port=self._smb_port.get(),
                    scan_dir=self._scan_dir.get(),
                    share_name=self._smb_share.get(),
                )
                self._smb_thread.start()
                self._smb_status.set("🟢")
                self._smb_btn.config(text="⏹ SMB")
                save_config(self._gather_config())
            except Exception as e:
                messagebox.showerror("Lỗi SMB", str(e))

    # ── Tray ──────────────────────────────────────────────────────────────────

    def _hide_to_tray(self):
        if not HAS_TRAY:
            messagebox.showwarning("Thiếu thư viện",
                                   "Cài pystray và Pillow để dùng tray:\n"
                                   "pip install pystray Pillow")
            return
        self.withdraw()

        menu = pystray.Menu(
            pystray.MenuItem("Mở ScanServer", self._show_from_tray, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Thoát", self._quit_from_tray),
        )
        icon_img = make_tray_icon()
        self._tray = pystray.Icon("ScanServer", icon_img, "ScanServer", menu)
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _show_from_tray(self, icon=None, item=None):
        if self._tray:
            self._tray.stop()
            self._tray = None
        self.after(0, self.deiconify)

    def _quit_from_tray(self, icon=None, item=None):
        if self._tray:
            self._tray.stop()
        self.after(0, self._quit)

    def _on_close(self):
        """Nhấn X → thu xuống tray nếu có server đang chạy."""
        running = (self._ftp_thread and self._ftp_thread.is_alive()) or \
                  (self._smb_thread and self._smb_thread.is_alive())
        if running and HAS_TRAY:
            self._hide_to_tray()
        else:
            self._quit()

    def _quit(self):
        if self._ftp_thread:
            self._ftp_thread.stop()
        if self._smb_thread:
            self._smb_thread.stop()
        # Lưu config trước khi thoát
        save_config(self._gather_config())
        self.destroy()
        sys.exit(0)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.disable(logging.CRITICAL)   # tắt log rác ra console
    app = App()
    app.mainloop()