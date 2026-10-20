@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Servidor.ps1" -Action Backup
pause
