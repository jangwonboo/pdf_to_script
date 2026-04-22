@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] python executable was not found in PATH.
  echo Install Python or add it to PATH, then try again.
  popd >nul
  exit /b 1
)

if "%~1"=="" (
  echo Usage: run.bat ^<PDF파일경로^> [options]
  echo Example: run.bat .\sample.pdf --verbose --log-file .\logs\run.log --ca-bundle .\corp-ca.pem
  echo Example^(insecure^): run.bat .\sample.pdf --insecure
  popd >nul
  exit /b 1
)

if exist "%SCRIPT_DIR%corp-ca.pem" (
  set "SSL_CERT_FILE=%SCRIPT_DIR%corp-ca.pem"
  set "REQUESTS_CA_BUNDLE=%SCRIPT_DIR%corp-ca.pem"
  echo [INFO] Using CA bundle: %SCRIPT_DIR%corp-ca.pem
)

python -m cli %*
set "EXIT_CODE=%ERRORLEVEL%"

popd >nul
exit /b %EXIT_CODE%
