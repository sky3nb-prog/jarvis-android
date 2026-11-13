@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Laufende Assistenten werden beendet, damit die Dateien ersetzt werden koennen ...
taskkill /f /im PC-Assistent.exe >nul 2>&1
taskkill /f /im PC-Assistent-Debug.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo === 0/3 Neueste Version von Jarvis holen ===
rem Holt die aktuellen Dateien von GitHub (Zweig "pc") und legt sie in diesen Ordner. Deine Einstellungen,
rem der Kopplungscode und alles andere bleiben, wie sie sind. Ohne Internet wird mit den vorhandenen Dateien gebaut.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; try { $here=(Get-Location).Path; $z=Join-Path $env:TEMP 'jarvis-pc.zip'; $d=Join-Path $env:TEMP 'jarvis-pc'; [Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest 'https://github.com/sky3nb-prog/jarvis-android/archive/refs/heads/pc.zip' -OutFile $z -UseBasicParsing; if (Test-Path $d) { Remove-Item $d -Recurse -Force }; Expand-Archive $z $d -Force; $src=(Get-ChildItem $d -Directory | Select-Object -First 1).FullName; $n=0; Get-ChildItem $src -Recurse -File | Where-Object { $_.Name -ne 'build.bat' -and $_.Name -ne '.gitignore' } | ForEach-Object { $rel=$_.FullName.Substring($src.Length+1); $t=Join-Path $here $rel; New-Item -ItemType Directory -Force (Split-Path $t) | Out-Null; Copy-Item $_.FullName $t -Force; $n++ }; Copy-Item (Join-Path $src 'build.bat') (Join-Path $here 'build.bat.neu') -Force; Write-Host ([string]$n + ' Dateien aktualisiert.') } catch { Write-Host ('Update nicht moeglich (' + $_.Exception.Message + ') - baue mit den vorhandenen Dateien.') }"
echo.

echo === 1/3 Benoetigte Pakete installieren ===
py -m pip install pyinstaller pystray pillow pyautogui sounddevice numpy SpeechRecognition tzdata
if errorlevel 1 goto fehler
rem Optional: Netzwerk-Anzeige im HUD (kein Problem, wenn das fehlschlaegt)
py -m pip install psutil >nul 2>&1
rem Optional: natuerliche Online-Stimmen (edge-tts)
py -m pip install -U edge-tts >nul 2>&1
rem Optional: Ausgabe-Auswahl auch fuer Online-Stimmen (soundfile)
py -m pip install soundfile >nul 2>&1
rem Optional: erkennen, was gerade laeuft (Musik/YouTube) fuer deine Interessen und die Handy-Fernbedienung
py -m pip install winsdk >nul 2>&1
py -m pip install winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation >nul 2>&1
rem Eigenes HUD-Fenster (statt Edge): pywebview mit der in Windows eingebauten Anzeige WebView2
py -m pip install -U pywebview >nul 2>&1
set EXTRA=--add-data "pc_web;pc_web"
py -c "import webview" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all webview --hidden-import clr
py -c "import clr_loader" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all clr_loader
py -c "import pythonnet" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all pythonnet
py -c "import edge_tts" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all edge_tts
py -c "import winsdk" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all winsdk
py -c "import winrt.windows.media.control" >nul 2>&1 && set EXTRA=%EXTRA% --collect-all winrt

echo.
echo === 2/3 Programm ohne Fenster bauen (PC-Assistent.exe) ===
py -m PyInstaller --onefile --noconsole --icon jarvis.ico --name PC-Assistent --collect-all speech_recognition %EXTRA% pc_overlay.py
if errorlevel 1 goto fehler

echo.
echo === 3/3 Testversion mit schwarzem Fenster bauen (PC-Assistent-Debug.exe) ===
py -m PyInstaller --onefile --icon jarvis.ico --name PC-Assistent-Debug --collect-all speech_recognition %EXTRA% pc_overlay.py
if errorlevel 1 goto fehler

echo.
echo Fertig! Die Programme liegen im Ordner "dist":
echo   dist\PC-Assistent.exe        (normal, laeuft unsichtbar im Hintergrund)
echo   dist\PC-Assistent-Debug.exe  (zeigt ein Fenster mit Meldungen, falls etwas nicht klappt)
pause
if exist "build.bat.neu" ( move /y "build.bat.neu" "build.bat" >nul & exit /b 0 )
exit /b 0

:fehler
echo.
echo Es ist ein Fehler aufgetreten. Mach einen Screenshot dieses Fensters.
pause
if exist "build.bat.neu" ( move /y "build.bat.neu" "build.bat" >nul & exit /b 1 )
exit /b 1
