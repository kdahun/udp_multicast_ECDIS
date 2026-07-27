@echo off
REM Windows 실행 파일(.exe) 빌드. Windows 에서 실행할 것.
setlocal
cd /d "%~dp0.."

py -3 -m venv .buildvenv
call .buildvenv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r packaging\requirements-build.txt

pyinstaller --noconfirm --clean build.spec

echo.
echo 빌드 완료 -^> dist\UDP-Multicast-ECDIS.exe
endlocal
