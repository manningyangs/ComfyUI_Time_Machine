# PyInstaller 打包脚本（Windows）
# 用法：pyinstaller build.spec --noconfirm

block_cipher = None

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

a = Analysis(
    ['src/comfyui_time_machine/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[
        # PySide6 需要的平台插件
    ],
    hiddenimports=[
        'PySide6',
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        'shiboken6',
        'comfyui_time_machine.ui',
        'comfyui_time_machine.ui.pages',
        'comfyui_time_machine.ui.workers',
        'comfyui_time_machine.snapshots.scope',
        'comfyui_time_machine.snapshots.store',
        'comfyui_time_machine.snapshots.manager',
        'comfyui_time_machine.snapshots.restore',
        'comfyui_time_machine.snapshots.diff',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='ComfyUI_Time_Machine',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,             # 调试：看崩溃栈
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ComfyUI_Time_Machine',
)
