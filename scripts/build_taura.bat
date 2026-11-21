@echo off
setlocal
set "ROOT=%~dp0.."
set "VC=C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
set "TAURI=C:\Users\HP\.cargo\bin\cargo-tauri.exe"
set "SDKROOT=C:\Program Files (x86)\Windows Kits\10"
if not exist "%VC%" goto :errvc
if not exist "%TAURI%" goto :errtaura
call "%VC%"
if errorlevel 1 exit /b 1

if not defined WindowsSdkDir set "WindowsSdkDir=%SDKROOT%\"
if not defined WindowsSDKVersion set "WindowsSDKVersion=10.0.26100.0\"
if exist "%WindowsSdkDir%Include\%WindowsSDKVersion%um\windows.h" goto :sdkready
for /f "delims=" %%v in ('dir /b /ad "%SDKROOT%\Include" 2^>nul') do set "WindowsSDKVersion=%%v\"
if not exist "%WindowsSdkDir%Include\%WindowsSDKVersion%um\windows.h" goto :errsdk

:sdkready
set "INCLUDE=%INCLUDE%;%WindowsSdkDir%Include\%WindowsSDKVersion%ucrt;%WindowsSdkDir%Include\%WindowsSDKVersion%um;%WindowsSdkDir%Include\%WindowsSDKVersion%shared;%WindowsSdkDir%Include\%WindowsSDKVersion%winrt;%WindowsSdkDir%Include\%WindowsSDKVersion%cppwinrt"
set "LIB=%LIB%;%WindowsSdkDir%Lib\%WindowsSDKVersion%ucrt\x64;%WindowsSdkDir%Lib\%WindowsSDKVersion%um\x64"

cd /d "%ROOT%\src-tauri"
"%TAURI%" build --bundles nsis
exit /b %ERRORLEVEL%

:errvc
echo MSVC vcvars64.bat not found: %VC%
exit /b 1
:errtaura
echo cargo-tauri.exe not found: %TAURI%
exit /b 1
:errsdk
echo Windows SDK um\windows.h not found
exit /b 1
