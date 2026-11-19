@echo off
setlocal
cd /d "%~dp0"	itle Perfume Scraper Dashboard
python -m pip install -e .
if errorlevel 1 (
  echo.
  echo Installation failed. Check Python installation and internet access.
  pause
  exit /b 1
)
python -m perfume_scraper.ui_server
