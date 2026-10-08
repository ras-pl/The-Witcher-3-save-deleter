@echo off
chcp 65001 >nul
title The Witcher 3 - Save Deleter
cd /d "%~dp0"

:: 1. Проверяем виртуальное окружение
if exist "venv\Scripts\python.exe" (
    set "PY=venv\Scripts\python.exe"
    goto START_APP
)

:: 2. Поиск Python в системе
python --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PY=python"
    goto CHECK_DEPS
)

py -3 --version >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set "PY=py -3"
    goto CHECK_DEPS
)

echo ========================================================
echo [ОШИБКА] Python не обнаружен в системе!
echo.
echo Пожалуйста, скачайте и установите Python 3:
echo https://www.python.org/downloads/
echo.
echo При установке ОБЯЗАТЕЛЬНО отметьте галочку:
echo "Add python.exe to PATH"
echo ========================================================
pause
exit /b 1

:CHECK_DEPS
:: 3. Проверка библиотек (Pillow и send2trash)
%PY% -c "import PIL" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] Установка зависимостей Pillow, send2trash...
    %PY% -m pip install -r requirements.txt
)

:START_APP
:: 4. Запуск программы
%PY% save_deleter.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ОШИБКА] Приложение завершилось с ошибкой.
    pause
)