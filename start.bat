@echo off
REM Neural Extractor starter

where python >nul 2>nul
if errorlevel 1 (
    echo Python is niet gevonden! Installeer eerst Python 3.11 of hoger en voeg toe aan PATH.
    pause
    exit /b
)

python main.py
pause 