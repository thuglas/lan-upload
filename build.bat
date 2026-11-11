@echo off
REM ------------------------------------------------------------------
REM  Build a portable, single-file Windows exe of upload_server.py
REM  Output: dist\lan-upload.exe
REM
REM  Requirements (build machine only): Python 3.9+ on PATH.
REM  A private virtual environment (.venv) is created so nothing is
REM  installed into your global Python.
REM ------------------------------------------------------------------
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")

if not exist ".venv\Scripts\python.exe" (
    echo Creating build virtual environment...
    %PY% -m venv .venv || goto :fail
)

echo Installing build tools...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet || goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements-build.txt --quiet || goto :fail

echo Building lan-upload.exe...
".venv\Scripts\python.exe" -m PyInstaller ^
    --onefile ^
    --console ^
    --clean ^
    --noconfirm ^
    --name lan-upload ^
    upload_server.py || goto :fail

echo.
echo Done:  %~dp0dist\lan-upload.exe
endlocal
exit /b 0

:fail
echo.
echo BUILD FAILED.
endlocal
exit /b 1
