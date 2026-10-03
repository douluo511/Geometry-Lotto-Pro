from pathlib import Path

project = Path(SPECPATH)
a = Analysis([str(project / 'updater_entry.py')], pathex=[str(project)], binaries=[],
             datas=[], hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='Psychology_Insight_Pro_Updater',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, disable_windowed_traceback=False)
