# -*- mode: python ; coding: utf-8 -*-
import sys
a = Analysis(['app.py'], pathex=[], binaries=[], datas=[], hiddenimports=['tkinter'], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DramaStudio', debug=False, bootloader_ignore_signals=False, strip=False, upx=True, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name='DramaStudio')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='DramaStudio.app', icon=None, bundle_identifier='com.local.dramastudio', info_plist={'NSRequiresAquaSystemAppearance': True})
