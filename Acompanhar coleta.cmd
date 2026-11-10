@echo off
setlocal
title DatumLex - Acompanhar coleta
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0scripts\status.ps1" -Watch
if errorlevel 1 (
    echo.
    echo O painel foi encerrado. Confira a mensagem acima.
    pause
    exit /b 1
)
