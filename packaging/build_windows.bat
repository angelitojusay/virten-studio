@echo off
rem Builds dist\Virten Studio (portable app) and, if Inno Setup 6 is installed, VirtenStudio-Setup-<version>.exe.
rem Run from anywhere:  packaging\build_windows.bat
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
    echo Run setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" -m pip install -q pyinstaller || goto :fail
copy /y icon.ico packaging\icon.ico >nul
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
".venv\Scripts\python.exe" -m PyInstaller --noconfirm packaging\autostyle.spec || goto :fail

for /f "usebackq delims=" %%v in (`.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, '.'); from autostyle import __version__; print(__version__)"`) do set VERSION=%%v
if "%VERSION%"=="" (echo Could not read the version. & goto :fail)
start "" /wait "dist\Virten Studio\Virten Studio.exe" --selftest
if errorlevel 1 (echo The packaged app failed its self-test: see %APPDATA%\Virten Studio\selftest.txt & goto :fail)
type "%APPDATA%\Virten Studio\selftest.txt"
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
    %ISCC% /DAppVersion=%VERSION% packaging\installer.iss || goto :fail
    ".venv\Scripts\python.exe" packaging\publish.py "dist\VirtenStudio-Setup-%VERSION%.exe" windows
) else (
    echo Inno Setup 6 not found: built the portable app in dist\Virten Studio only.
)
echo Done.
exit /b 0
:fail
echo Build failed.
exit /b 1
