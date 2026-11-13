@echo off
setlocal
cd /d "%~dp0"
set OUT=dist\X1Companion
if not exist "%OUT%" mkdir "%OUT%"
xcopy /E /I /Y core  "%OUT%\core"  >nul
xcopy /E /I /Y ui    "%OUT%\ui"    >nul
xcopy /E /I /Y tools "%OUT%\tools" >nul
xcopy /E /I /Y tests "%OUT%\tests" >nul
copy /Y main.py                "%OUT%\" >nul
copy /Y README.md              "%OUT%\" >nul
copy /Y LICENSE-THIRD-PARTY.md "%OUT%\" >nul
copy /Y config.example.json    "%OUT%\" >nul
copy /Y requirements.txt       "%OUT%\" >nul
>  "%OUT%\run.bat" echo @echo off
>> "%OUT%\run.bat" echo cd /d "%%~dp0"
>> "%OUT%\run.bat" echo python main.py %%*
echo.
echo [X1 Companion] Portable folder ready: %OUT%
echo No PyInstaller needed - pure Python standard library.
echo Run it with:  cd %OUT% ^&^& run.bat
endlocal
