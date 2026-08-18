@echo off
setlocal
set PYINSTALLER_CONFIG_DIR=.pyinstaller-cache
python -m PyInstaller --clean --noconfirm DramaStudio.spec
if errorlevel 1 exit /b %errorlevel%
echo Built dist\DramaStudio-Text-Production\DramaStudio-Text-Production.exe
