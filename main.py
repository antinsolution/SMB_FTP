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
    "ftp_dir": os.path.expanduser("~/Scans"),
    "ftp_port": 2121,
    "ftp_user": "scanner",
    "ftp_pass": "1234",
    "ftp_enabled": False,
    "smb_dir": os.path.expanduser("~/Scans"),
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
        # Expand ~ trong đường dẫn
        for key in ("ftp_dir", "smb_dir"):
            val = merged.get(key, "")
            if val.startswith("~"):
                merged[key] = os.path.expanduser(val)
        return merged
    except (FileNotFoundError, json.JSONDecodeError):
        return DEFAULT_CONFIG.copy()


def save_config(data):
    try:
        # Resolve paths to portable form before saving
        data = dict(data)
        for key in ("ftp_dir", "smb_dir"):
            val = data.get(key, "")
            if val.startswith(os.path.expanduser("~")):
                data[key] = val.replace(os.path.expanduser("~"), "~")
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
        PAD = dict(padx=10, pady=5)
        IPAD = dict(padx=3, pady=0)

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        # ── Tab FTP ──────────────────────────────────────────────────────────
        ftp_frame = ttk.Frame(nb)
        nb.add(ftp_frame, text="  FTP Server  ")

        self._ftp_enabled = tk.BooleanVar(value=self._config.get("ftp_enabled", False))
        ttk.Checkbutton(ftp_frame, text="Bật FTP Server",
                        variable=self._ftp_enabled).grid(row=0, column=0, columnspan=3,
                                                          sticky="w", **PAD)

        self._ftp_dir = tk.StringVar(value=self._config.get("ftp_dir", os.path.expanduser("~/Scans")))
        ttk.Label(ftp_frame, text="Thư mục:").grid(row=1, column=0, sticky="w", **PAD)
        ttk.Entry(ftp_frame, textvariable=self._ftp_dir, width=32).grid(row=1, column=1, **PAD)
        ttk.Button(ftp_frame, text="…", width=3,
                   command=lambda: self._browse(self._ftp_dir)).grid(row=1, column=2, **PAD)

        self._ftp_port = tk.IntVar(value=self._config.get("ftp_port", 21))
        ttk.Label(ftp_frame, text="Port:").grid(row=2, column=0, sticky="w", **PAD)
        ttk.Spinbox(ftp_frame, from_=1, to=65535, textvariable=self._ftp_port,
                    width=8).grid(row=2, column=1, sticky="w", **PAD)

        self._ftp_user = tk.StringVar(value=self._config.get("ftp_user", "scanner"))
        ttk.Label(ftp_frame, text="Username:").grid(row=3, column=0, sticky="w", **PAD)
        ttk.Entry(ftp_frame, textvariable=self._ftp_user, width=18).grid(row=3, column=1,
                                                                            sticky="w", **PAD)

        self._ftp_pass = tk.StringVar(value=self._config.get("ftp_pass", "1234"))
        ttk.Label(ftp_frame, text="Password:").grid(row=4, column=0, sticky="w", **PAD)
        ttk.Entry(ftp_frame, textvariable=self._ftp_pass, show="*", width=18).grid(
            row=4, column=1, sticky="w", **PAD)

        self._ftp_status = tk.StringVar(value="⚪ Chưa chạy")
        ttk.Label(ftp_frame, textvariable=self._ftp_status,
                  foreground="gray").grid(row=5, column=0, columnspan=3, **PAD)

        self._ftp_btn = ttk.Button(ftp_frame, text="▶ Khởi động FTP",
                                   command=self._toggle_ftp)
        self._ftp_btn.grid(row=6, column=0, columnspan=3, pady=(2, 10))

        # ── Tab SMB ──────────────────────────────────────────────────────────
        smb_frame = ttk.Frame(nb)
        nb.add(smb_frame, text="  SMB Server  ")

        self._smb_enabled = tk.BooleanVar(value=self._config.get("smb_enabled", False))
        ttk.Checkbutton(smb_frame, text="Bật SMB Server",
                        variable=self._smb_enabled).grid(row=0, column=0, columnspan=3,
                                                          sticky="w", **PAD)

        self._smb_dir = tk.StringVar(value=self._config.get("smb_dir", os.path.expanduser("~/Scans")))
        ttk.Label(smb_frame, text="Thư mục:").grid(row=1, column=0, sticky="w", **PAD)
        ttk.Entry(smb_frame, textvariable=self._smb_dir, width=32).grid(row=1, column=1, **PAD)
        ttk.Button(smb_frame, text="…", width=3,
                   command=lambda: self._browse(self._smb_dir)).grid(row=1, column=2, **PAD)

        self._smb_port = tk.IntVar(value=self._config.get("smb_port", 139))
        ttk.Label(smb_frame, text="Port:").grid(row=2, column=0, sticky="w", **PAD)
        ttk.Spinbox(smb_frame, from_=1, to=65535, textvariable=self._smb_port,
                    width=8).grid(row=2, column=1, sticky="w", **PAD)

        self._smb_share = tk.StringVar(value=self._config.get("smb_share", "SCANS"))
        ttk.Label(smb_frame, text="Share name:").grid(row=3, column=0, sticky="w", **PAD)
        ttk.Entry(smb_frame, textvariable=self._smb_share, width=18).grid(row=3, column=1,
                                                                             sticky="w", **PAD)

        ttk.Label(smb_frame, text="⚠ SMB không yêu cầu mật khẩu (guest mode)",
                  foreground="orange").grid(row=4, column=0, columnspan=3, **PAD)

        self._smb_status = tk.StringVar(value="⚪ Chưa chạy")
        ttk.Label(smb_frame, textvariable=self._smb_status,
                  foreground="gray").grid(row=5, column=0, columnspan=3, **PAD)

        self._smb_btn = ttk.Button(smb_frame, text="▶ Khởi động SMB",
                                   command=self._toggle_smb)
        self._smb_btn.grid(row=6, column=0, columnspan=3, pady=(2, 10))

        # ── Bottom bar ────────────────────────────────────────────────────────
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=10, pady=(0, 8))

        # IP label bên trái
        local_ip = get_local_ip()
        ip_label = ttk.Label(bar, text=f"🌐 IP: {local_ip}", foreground="#2563EB")
        ip_label.pack(side="left", **IPAD)

        ttk.Button(bar, text="Thu nhỏ xuống khay",
                   command=self._hide_to_tray).pack(side="left", padx=(10, 0))
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
            "ftp_dir": self._ftp_dir.get(),
            "ftp_port": self._ftp_port.get(),
            "ftp_user": self._ftp_user.get(),
            "ftp_pass": self._ftp_pass.get(),
            "ftp_enabled": (self._ftp_thread is not None and self._ftp_thread.is_alive()),
            "smb_dir": self._smb_dir.get(),
            "smb_port": self._smb_port.get(),
            "smb_share": self._smb_share.get(),
            "smb_enabled": (self._smb_thread is not None and self._smb_thread.is_alive()),
        }

    # ── FTP toggle ────────────────────────────────────────────────────────────

    def _toggle_ftp(self):
        if self._ftp_thread and self._ftp_thread.is_alive():
            self._ftp_thread.stop()
            self._ftp_thread = None
            self._ftp_status.set("⚪ Đã dừng")
            self._ftp_btn.config(text="▶ Khởi động FTP")
            self._ftp_enabled.set(False)
            save_config(self._gather_config())
        else:
            if not HAS_FTP:
                messagebox.showerror("Lỗi", "Chưa cài pyftpdlib.\npip install pyftpdlib")
                return
            try:
                self._ftp_thread = FTPThread(
                    host="0.0.0.0",
                    port=self._ftp_port.get(),
                    scan_dir=self._ftp_dir.get(),
                    user=self._ftp_user.get(),
                    password=self._ftp_pass.get(),
                )
                self._ftp_thread.start()
                self._ftp_status.set(
                    f"🟢 Đang chạy – 0.0.0.0:{self._ftp_port.get()}")
                self._ftp_btn.config(text="⏹ Dừng FTP")
                self._ftp_enabled.set(True)
                save_config(self._gather_config())
            except Exception as e:
                messagebox.showerror("Lỗi FTP", str(e))

    # ── SMB toggle ────────────────────────────────────────────────────────────

    def _toggle_smb(self):
        if self._smb_thread and self._smb_thread.is_alive():
            self._smb_thread.stop()
            self._smb_thread = None
            self._smb_status.set("⚪ Đã dừng")
            self._smb_btn.config(text="▶ Khởi động SMB")
            self._smb_enabled.set(False)
            save_config(self._gather_config())
        else:
            if not HAS_SMB:
                messagebox.showerror("Lỗi", "Chưa cài impacket.\npip install impacket")
                return
            try:
                self._smb_thread = SMBThread(
                    host="0.0.0.0",
                    port=self._smb_port.get(),
                    scan_dir=self._smb_dir.get(),
                    share_name=self._smb_share.get(),
                )
                self._smb_thread.start()
                self._smb_status.set(
                    f"🟢 Đang chạy – \\\\<IP>\\{self._smb_share.get().upper()}")
                self._smb_btn.config(text="⏹ Dừng SMB")
                self._smb_enabled.set(True)
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