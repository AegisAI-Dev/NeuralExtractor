@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"

REM Check of de standalone EXE bestaat
if exist "dist\NeuralExtractor.exe" (
    echo Starten van Neural Extractor (Standalone)...
    start "" "dist\NeuralExtractor.exe"
    exit /b 0
)

echo ============================================
echo   Neural Extractor - Starten vanuit broncode
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [FOUT] Python niet gevonden en geen standalone EXE gevonden in de dist map!
    echo Draai build.bat om de EXE te bouwen, of installeer Python.
    echo.
    pause
    exit /b 1
)

python "%~dp0main.py"
pause