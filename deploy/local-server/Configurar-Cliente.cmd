@echo off
cd /d "%~dp0"
echo Este arquivo instala o certificado HTTPS do servidor DatumLex neste usuario.
echo Execute somente a copia fornecida pelo responsavel pelo servidor.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Configurar-Cliente.ps1"
if errorlevel 1 goto failure
start "" "%~dp0DatumLex.url"
exit /b 0
:failure
echo Nao foi possivel instalar o certificado.
pause
exit /b 1
