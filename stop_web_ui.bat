@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_web_ui.ps1"
if errorlevel 1 pause
