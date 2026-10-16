@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Passcode
set PY=
where py >nul 2>nul && set PY=py
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY (
  echo No se encontro Python. Instalalo desde https://www.python.org/downloads/ ^(tilda "Add python.exe to PATH"^) y volve a abrir este archivo.
  pause
  exit /b 1
)
%PY% --version
if not exist venv\Scripts\python.exe (
  echo Creando entorno virtual...
  %PY% -m venv venv || ( echo Error creando el entorno & pause & exit /b 1 )
)
echo Instalando dependencias...
venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt || ( echo Error instalando dependencias & pause & exit /b 1 )
echo.
echo Abriendo http://localhost:5000 ...  (cerra esta ventana para apagar la app)
start "" cmd /c "timeout /t 4 >nul & start http://localhost:5000"
set BASE_URL=http://localhost:5000
venv\Scripts\python.exe run.py
pause
