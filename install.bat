@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"

echo ============================================
echo   Neural Extractor - Installatie
echo ============================================
echo.

if exist "dist\NeuralExtractor.exe" (
    echo [OK] Standalone EXE gevonden! Er hoeft niets geinstalleerd te worden.
    echo Je kunt de app direct starten via start.bat of dist\NeuralExtractor.exe
    echo.
    pause
    exit /b 0
)

REM --- Python detectie ---
where python >nul 2>nul
if errorlevel 1 (
    echo [FOUT] Python niet gevonden!
    echo.
    echo Installeer Python 3.10+ van https://www.python.org/downloads/
    echo BELANGRIJK: Vink "Add Python to PATH" aan tijdens installatie!
    echo.
    echo Na installatie: sluit dit venster en dubbelklik opnieuw op install.bat
    echo.
    pause
    exit /b 1
)

REM --- Python versie check (3.10+) ---
python -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)" 2>nul
if errorlevel 1 (
    echo [FOUT] Python 3.10 of hoger is vereist!
    echo Huidige versie:
    python --version
    echo.
    echo Download de nieuwste versie van https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo [OK] Python gevonden:
python --version
echo.

REM --- pip upgrade ---
echo Pip bijwerken...
python -m pip install --upgrade pip >nul 2>nul
echo.

REM --- Dependencies installeren ---
echo Installeren van dependencies...
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo Normaal installeren mislukt, probeer met --user...
    python -m pip install --user -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo [FOUT] Kon dependencies niet installeren!
        pause
        exit /b 1
    )
)
echo.
echo [OK] Alle dependencies geinstalleerd! Je kunt nu start.bat gebruiken of build.bat uitvoeren.
echo.
pause