@echo off
REM Neural Extractor installer & starter

where python >nul 2>nul
if errorlevel 1 (
    echo Python is niet gevonden! Installeer eerst Python 3.11 of hoger en voeg toe aan PATH.
    pause
    exit /b
)

where pip >nul 2>nul
if errorlevel 1 (
    echo Pip is niet gevonden! Installeer pip voor Python 3.11 of hoger.
    pause
    exit /b
)

pip install --upgrade pip
pip install -r requirements.txt

python main.py
pause 