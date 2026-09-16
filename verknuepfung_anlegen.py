# -*- coding: utf-8 -*-
"""
verknuepfung_anlegen.py
Legt die Desktop-Verknüpfung «Fotos sortieren» (mit Logo) an – ohne PowerShell.
Aufruf: Doppelklick auf diese Datei  oder  python verknuepfung_anlegen.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ORDNER = Path(__file__).resolve().parent
def _neueste_app():
    """Neueste Programmdatei Fotosortierprogramm_vX.Y.pyw im Ordner."""
    import re
    kandidaten = list(ORDNER.glob("Fotosortierprogramm_v*.pyw"))
    def version(p):
        m = re.search(r"_v(\d+)\.(\d+)", p.stem)
        return (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    return max(kandidaten, key=version) if kandidaten else ORDNER / "Fotosortierprogramm_v0.0.pyw"


APP = ORDNER / "Fotos_sortieren_start.pyw"
ICON = ORDNER / "fotos_sortieren.ico"


def desktop_pfad() -> Path:
    """Echter Desktop-Ordner (berücksichtigt OneDrive-Umleitung) aus der Registry."""
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                           r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        wert, _ = winreg.QueryValueEx(k, "Desktop")
        return Path(os.path.expandvars(wert))
    except Exception:
        return Path.home() / "Desktop"


def pythonw_pfad() -> str:
    kandidat = Path(sys.executable).with_name("pythonw.exe")
    return str(kandidat if kandidat.exists() else sys.executable)


def main():
    if not sys.platform.startswith("win"):
        print("Dieses Script ist nur für Windows gedacht.")
        return
    if not APP.exists():
        print("FEHLER: Fotos_sortieren_start.pyw nicht gefunden – dieses Script muss im Programmordner liegen.")
        input("Enter zum Schliessen ...")
        return

    desktop = desktop_pfad()
    desktop.mkdir(parents=True, exist_ok=True)
    lnk = desktop / "Fotos sortieren.lnk"

    # VBScript nutzt den Windows-Script-Host, der auf jedem Windows vorhanden ist
    vbs = f'''
Set ws = CreateObject("WScript.Shell")
Set s = ws.CreateShortcut("{lnk}")
s.TargetPath = "{pythonw_pfad()}"
s.Arguments = """{APP}"""
s.WorkingDirectory = "{ORDNER}"
s.IconLocation = "{ICON},0"
s.Description = "Fotos nach Datum, Ort und Thema sortieren"
s.Save
'''
    with tempfile.NamedTemporaryFile("w", suffix=".vbs", delete=False, encoding="utf-8") as f:
        f.write(vbs)
        vbs_datei = f.name
    try:
        r = subprocess.run(["cscript", "//nologo", vbs_datei], capture_output=True, text=True)
    finally:
        try:
            os.remove(vbs_datei)
        except OSError:
            pass

    if lnk.exists():
        print(f"Verknüpfung erstellt:\n  {lnk}")
        print(f"Startet: {pythonw_pfad()}  {APP}")
        print("\nErscheint das Symbol nicht sofort, auf dem Desktop F5 drücken.")
    else:
        print("Verknüpfung konnte nicht erstellt werden.")
        print(r.stdout, r.stderr)
        print("\nErsatz: Rechtsklick auf die Datei Fotosortierprogramm_v*.pyw → «Senden an» → «Desktop (Verknüpfung erstellen)».")
    input("\nEnter zum Schliessen ...")


if __name__ == "__main__":
    main()
