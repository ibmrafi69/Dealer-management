# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


project_root = Path(SPECPATH)
datas = [
    (str(project_root / 'templates'), 'templates'),
    (str(project_root / 'static'), 'static'),
]
media_root = project_root / 'media'
if media_root.exists():
    datas.append((str(media_root), 'seed_media'))

hiddenimports = collect_submodules('django.core.management.commands')
for app_name in ('dealers', 'products', 'sales', 'inventory', 'reports', 'godown_stock'):
    hiddenimports.extend(collect_submodules(app_name))
    # This project currently keeps its shared assets at the project root, but
    # package any future app-local Django resources as well.
    for resource_name in ('templates', 'static', 'locale'):
        resource_root = project_root / app_name / resource_name
        if resource_root.exists():
            datas.append((str(resource_root), str(Path(app_name) / resource_name)))
datas.extend(collect_data_files('django'))
# PDF exports import ReportLab within view functions, so collect its dynamic
# modules and package data explicitly for frozen builds.
hiddenimports.extend(collect_submodules('reportlab'))
datas.extend(collect_data_files('reportlab'))

a = Analysis(
    ['launcher.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# PyInstaller's Django hook discovers the development SQLite database from the
# active settings. It must never enter the distributable: frozen installs use
# the external per-user database prepared by launcher.py instead.
a.datas = [entry for entry in a.datas if Path(entry[0]).name.lower() != "db.sqlite3"]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Dealer Management',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Dealer Management',
)
