# -*- coding: utf-8 -*-
"""
Fotos_sortieren_start.pyw – feste Startdatei (nie ersetzen).
Die Desktop-Verknüpfung zeigt hierher. Diese Datei sucht die neueste
Fotosortierprogramm_vX.Y.pyw im selben Ordner und startet sie.
Neue Version einspielen = neue .pyw-Datei in diesen Ordner kopieren, sonst nichts.
"""
import re
import runpy
import sys
from pathlib import Path

ORDNER = Path(__file__).resolve().parent


def neueste_version():
    def version(p):
        # Versionsnummer aus dem Dateinamen, z. B. _v2.12.1 -> (2, 12, 1); _v2.12 -> (2, 12, 0)
        m = re.search(r"_v(\d+(?:\.\d+)*)", p.stem)
        if not m:
            return (0,)
        teile = [int(x) for x in m.group(1).split(".")]
        return tuple(teile + [0] * (3 - len(teile)))
    kandidaten = [p for p in ORDNER.glob("Fotosortierprogramm_v*.pyw") if version(p) > (0,)]
    return max(kandidaten, key=version) if kandidaten else None


if __name__ == "__main__":
    app = neueste_version()
    if app is None:
        import tkinter as tk
        from tkinter import messagebox
        w = tk.Tk(); w.withdraw()
        messagebox.showerror("Fotosortierprogramm",
                             f"Keine Datei Fotosortierprogramm_vX.Y.pyw gefunden in:\n{ORDNER}")
        sys.exit(1)
    sys.path.insert(0, str(ORDNER))
    sys.argv = [str(app)]
    runpy.run_path(str(app), run_name="__main__")
