# -*- mode: python ; coding: utf-8 -*-

import os
import sys

block_cipher = None

# ── Include config.json và icon.ico vào trong bản build ──────────────────────
datas = []
if os.path.exists('config.json'):
    datas.append(('config.json', '.'))
if os.path.exists('icon.ico'):
    datas.append(('icon.ico', '.'))

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # Dependencies thực tế của project
        'pyftpdlib',
        'pyftpdlib.handlers',
        'pyftpdlib.servers',
        'pyftpdlib.authorizers',
        'impacket',
        'impacket.smbserver',
        'pystray',
        'PIL',
        'PIL._tkinter_finder',
        'PIL.Image',
        'PIL.ImageDraw',
        # Core Python modules cần thiết
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'socket',
        'threading',
        'json',
        'logging',
        'os',
        'sys',
        'ctypes',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude các module Linux/macOS không cần trên Windows
        'AppKit',
        'Foundation',
        'PyObjCTools',
        'objc',
        'gi',
        'Xlib',
        'tkinter.test',
        'tkinter.tix',
        'unittest',
        'setuptools',
        'pip',
        'smtplib',
        'imaplib',
        'httpcore',
        'httpx',
        'aioquic',
        'anyio',
        'trio',
        'ldap3',
        'ldapdomaindump',
        'dns',
        'readline',
        'cffi',
        'Cryptodome',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SMB_FTP_SV',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon='icon.ico',
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='SMB_FTP_SV',
)