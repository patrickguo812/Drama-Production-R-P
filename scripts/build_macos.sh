#!/bin/sh
set -eu
PYINSTALLER_CONFIG_DIR=.pyinstaller-cache python3 -m PyInstaller --clean --noconfirm DramaStudio.spec
echo "Built dist/Drama Studio - Text Production.app"
