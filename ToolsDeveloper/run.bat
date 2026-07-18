@echo off
REM Launch the SLM332L Protocol Tester GUI.
cd /d "%~dp0"
python -m slm332l_tester
if errorlevel 1 pause
