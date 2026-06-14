@echo off
chcp 65001 >nul 2>nul
echo ============================================
echo   Neural Extractor - Build Standalone EXE
echo ============================================
echo.

cd /d "%~dp0"

echo 1. Installeren van vereiste build tools...
python -m pip install pyinstaller
if errorlevel 1 (
    echo [FOUT] Kon PyInstaller niet installeren.
    pause
    exit /b 1
)
echo.

echo 2. Dependencies installeren...
python -m pip install -r requirements.txt
echo.

echo 3. Bouwen van de EXE met PyInstaller...
python -m PyInstaller NeuralExtractor.spec --clean
if errorlevel 1 (
    echo [FOUT] Build proces is mislukt!
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Build succesvol!
echo ============================================
echo De standalone EXE staat in de 'dist' map.
echo.
pause
