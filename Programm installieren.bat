@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul
title Fotosortierprogramm - Installation
cd /d "%~dp0"

echo ==================================================================
echo   FOTOSORTIERPROGRAMM - Installation
echo ==================================================================
echo.
echo Diese Installation
echo   1. prueft Python und installiert es bei Bedarf (ca. 30 MB Download)
echo   2. kopiert das Programm in einen Ordner Ihrer Wahl
echo   3. legt Standardordner fuer sortierte Fotos und Doppelbilder an
echo   4. installiert die benoetigten Module (ohne KI ca. 30 MB, mit KI ca. 400 MB)
echo   5. legt das Desktop-Symbol "Fotos sortieren" an
echo.
echo Bei Rueckfragen genuegt Enter fuer die Vorgabe in eckigen Klammern.
echo.

rem ---------------------------------------------------------------- 1. Python
set "PY="
for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if defined PY (
    "%PY%" -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
    if errorlevel 1 set "PY="
)
if not defined PY if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY (
    echo [1/5] Python nicht gefunden - wird jetzt heruntergeladen und installiert ...
    set "PYINST=%TEMP%\python-3.12.10-amd64.exe"
    curl -L -o "!PYINST!" https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe
    if errorlevel 1 (
        echo FEHLER: Download fehlgeschlagen. Bitte Python manuell installieren: https://www.python.org/downloads/
        echo         Beim Installieren "Add python.exe to PATH" anhaken, danach diese Datei erneut ausfuehren.
        pause
        exit /b 1
    )
    "!PYINST!" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1
    set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
    if not exist "!PY!" (
        echo FEHLER: Python-Installation fehlgeschlagen. Bitte manuell installieren und erneut ausfuehren.
        pause
        exit /b 1
    )
    echo       Python installiert.
) else (
    for /f "usebackq delims=" %%v in (`"%PY%" -c "import sys;print(sys.version.split()[0])"`) do echo [1/5] Python %%v gefunden.
)
for %%p in ("%PY%") do set "PYW=%%~dpppythonw.exe"
if not exist "%PYW%" set "PYW=%PY%"
echo.

rem ---------------------------------------------------------------- 2. Installationsordner
set "ZIELPROG=%USERPROFILE%\Documents\Programm_FotoSortieren"
set "EINGABE="
set /p EINGABE="[2/5] Installationsordner [%ZIELPROG%]: "
if not "%EINGABE%"=="" set "ZIELPROG=%EINGABE%"
if not exist "%ZIELPROG%" mkdir "%ZIELPROG%"
if not exist "%ZIELPROG%" (
    echo FEHLER: Ordner konnte nicht angelegt werden: %ZIELPROG%
    pause
    exit /b 1
)
for %%f in (Fotos_sortieren_start.pyw Fotosortierprogramm_v*.pyw fotosortierer_kern.py fotos_sortieren.ico verknuepfung_anlegen.py ANLEITUNG.txt "Programm installieren.bat") do (
    copy /y "%%~f" "%ZIELPROG%" >nul
)
rem Windows-Sperre fuer heruntergeladene Dateien aufheben
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%ZIELPROG%' -File | Unblock-File" >nul 2>&1
echo       Programm kopiert nach %ZIELPROG%
echo.

rem ---------------------------------------------------------------- 3. Standardordner
set "ZIELFOTO=%USERPROFILE%\Fotos_sortiert"
set "EINGABE="
set /p EINGABE="[3/5] Ordner fuer sortierte Fotos [%ZIELFOTO%]: "
if not "%EINGABE%"=="" set "ZIELFOTO=%EINGABE%"
set "DOPPEL=%ZIELFOTO%\Aussortierte_Doppelbilder"
if not exist "%ZIELFOTO%" mkdir "%ZIELFOTO%"
if not exist "%DOPPEL%" mkdir "%DOPPEL%"
"%PY%" -c "import json,sys,pathlib; p=pathlib.Path(sys.argv[1])/'einstellungen.json'; e=json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}; e['ziel']=sys.argv[2]; e['doppel_ordner']=sys.argv[3]; p.write_text(json.dumps(e,ensure_ascii=False,indent=1),encoding='utf-8')" "%ZIELPROG%" "%ZIELFOTO%" "%DOPPEL%"
echo       Zielordner:        %ZIELFOTO%
echo       Doppelbilder:      %DOPPEL%
echo       (Beide Ordner koennen im Programm unter "1. Ordner" jederzeit geaendert werden.)
echo.

rem ---------------------------------------------------------------- 4. Module
echo [4/5] Module installieren (Internet noetig) ...
"%PY%" -m pip install --upgrade pip >nul 2>&1
"%PY%" -m pip install --quiet pillow pillow-heif requests openpyxl
if errorlevel 1 (
    echo FEHLER bei der Installation der Grundmodule. Internetverbindung pruefen und erneut ausfuehren.
    pause
    exit /b 1
)
echo       Grundmodule installiert (Datum, Ort, Doppelbilder, Excel).
set "KI=J"
set /p KI="      KI-Module fuer die Themensortierung installieren? (ca. 400 MB) [J/n]: "
if /i "%KI%"=="N" (
    echo       Uebersprungen. Spaeter nachholen: "%PY%" -m pip install torch open_clip_torch transformers sentencepiece
) else (
    "%PY%" -m pip install --quiet torch open_clip_torch transformers sentencepiece
    if errorlevel 1 (
        echo WARNUNG: KI-Module konnten nicht installiert werden - Datum/Ort/Doppelbilder funktionieren trotzdem.
    ) else (
        echo       KI-Module installiert. Das KI-Modell selbst ^(ca. 1.1 GB^) wird beim ersten Lauf mit Themensortierung geladen.
    )
)
echo.

rem ---------------------------------------------------------------- 5. Desktop-Symbol
echo [5/5] Desktop-Symbol anlegen ...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d=[Environment]::GetFolderPath('Desktop');" ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\Fotos sortieren.lnk\");" ^
  "$s.TargetPath='%PYW%';" ^
  "$s.Arguments='\"%ZIELPROG%\Fotos_sortieren_start.pyw\"';" ^
  "$s.WorkingDirectory='%ZIELPROG%';" ^
  "$s.IconLocation='%ZIELPROG%\fotos_sortieren.ico,0';" ^
  "$s.Description='Fotos nach Datum, Ort und Thema sortieren';" ^
  "$s.Save(); Write-Host ('      Verknuepfung erstellt: ' + $d + '\Fotos sortieren.lnk')"
echo.
echo ==================================================================
echo   Installation abgeschlossen.
echo   Start: Doppelklick auf das Desktop-Symbol "Fotos sortieren".
echo   Beim ersten Start unter "1. Ordner" den Quellordner mit den Fotos
echo   waehlen; Ziel- und Doppelbilder-Ordner sind bereits eingetragen.
echo ==================================================================
pause
