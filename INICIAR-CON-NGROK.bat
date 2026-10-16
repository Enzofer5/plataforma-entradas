@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Passcode + ngrok
echo ==========================================================
echo  PASSCODE CON NGROK  (cerra antes la otra ventana de Passcode)
echo ==========================================================
echo.

rem --- 1) buscar ngrok (en el PATH, donde lo deja winget o en la carpeta local) ---
set "NGROK="
set "NGDIR=%LOCALAPPDATA%\ngrok-bin"
rem Primero el ngrok descargado de la pagina oficial (version nueva).
if exist "%NGDIR%\ngrok.exe" set "NGROK=%NGDIR%\ngrok.exe"
if not defined NGROK for /f "delims=" %%i in ('where ngrok 2^>nul') do if not defined NGROK set "NGROK=%%i"
if not defined NGROK if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe" set "NGROK=%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe"
if not defined NGROK (
  echo ngrok no esta instalado. Instalandolo...
  winget install -e --id Ngrok.Ngrok --source winget --accept-source-agreements --accept-package-agreements
  if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe" set "NGROK=%LOCALAPPDATA%\Microsoft\WinGet\Links\ngrok.exe"
)
if not defined NGROK (
  echo Descargando ngrok desde la pagina oficial...
  if not exist "%NGDIR%" mkdir "%NGDIR%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri 'https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-windows-amd64.zip' -OutFile \"$env:TEMP\ngrok.zip\"; Expand-Archive -Force \"$env:TEMP\ngrok.zip\" \"$env:LOCALAPPDATA\ngrok-bin\""
  if exist "%NGDIR%\ngrok.exe" set "NGROK=%NGDIR%\ngrok.exe"
)
if not defined NGROK (
  echo.
  echo No se pudo instalar ngrok. Avisale a Claude.
  pause
  exit /b 1
)
echo ngrok: %NGROK%
"%NGROK%" update >nul 2>nul

rem --- 2) authtoken configurado? ---
"%NGROK%" config check >nul 2>nul
findstr /i "authtoken" "%LOCALAPPDATA%\ngrok\ngrok.yml" >nul 2>nul
if errorlevel 1 (
  echo.
  echo Falta tu Authtoken de ngrok.
  echo Copialo de https://dashboard.ngrok.com/get-started/your-authtoken
  set /p TOKEN=Pegalo aca con CLIC DERECHO y apreta Enter: 
  call "%NGROK%" config add-authtoken %%TOKEN%%
  echo.
)

rem --- 3) dominio fijo ---
set "DOMINIO="
if exist ngrok-dominio.txt set /p DOMINIO=<ngrok-dominio.txt
if not defined DOMINIO (
  echo Escribi tu dominio de ngrok ^(panel de ngrok - Domains^), ejemplo: tu-nombre.ngrok-free.dev
  set /p DOMINIO=Dominio: 
)
set "DOMINIO=%DOMINIO:https://=%"
set "DOMINIO=%DOMINIO:/=%"
set "DOMINIO=%DOMINIO: =%"
> ngrok-dominio.txt echo %DOMINIO%

rem --- 4) entorno de Python ---
set PY=
where py >nul 2>nul && set PY=py
if not defined PY ( where python >nul 2>nul && set PY=python )
if not exist venv\Scripts\python.exe ( %PY% -m venv venv )
venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt

rem --- 5) arrancar ngrok (su ventana queda abierta si falla; todo queda en ngrok.log) ---
set BASE_URL=https://%DOMINIO%
echo.
echo Abriendo el tunel: %BASE_URL%  -^> localhost:5000
if exist ngrok.log del ngrok.log >nul 2>nul
start "ngrok" cmd /k ""%NGROK%" http --url=%BASE_URL% 5000 --log "%~dp0ngrok.log" --log-format logfmt"
start "" cmd /c "timeout /t 8 >nul & start %BASE_URL%"
echo La app queda en %BASE_URL%  (si ngrok muestra un aviso, toca "Visit Site")
echo Para apagar: cerra esta ventana y la de ngrok.
echo.
venv\Scripts\python.exe run.py
pause
