@echo off
REM Launch the SLM332L Protocol Tester - modern Qt (PySide6) UI.
cd /d "%~dp0"
python -m slm332l_tester.qt_app
if errorlevel 1 pause
