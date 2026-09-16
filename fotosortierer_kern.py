# -*- coding: utf-8 -*-
"""
fotosortierer_kern.py – Logik des Programms «Fotos sortieren»
(wird von Fotosortierprogramm_vX.Y.pyw verwendet, kann aber auch ohne Oberfläche laufen)

Sortiert Fotos aus einem Quellordner (inkl. Unterordner) in einen Zielordner:
  nach_Datum/JJJJ/JJJJ-MM/          Aufnahmedatum aus EXIF
  nach_Ort/<Land>/<Ort>/            GPS aus EXIF + OpenStreetMap-Abfrage
  nach_Thema/<Kategorie>/           Bildinhalt, lokales KI-Modell (CLIP), Kategorien frei definierbar
  nach_Thema/Panorama/              Seitenverhältnis
Originale werden nicht verändert (Kopie), ausser «verschieben» ist gewählt.
"""

import csv
import json
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ExifTags

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_OK = True
except ImportError:
    HEIF_OK = False

try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

BILD_ENDUNGEN = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".heif", ".webp"}
VIDEO_ENDUNGEN = {".mp4", ".mov", ".avi", ".m4v"}

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = "FotosSortieren/2.0 (privates Sortierprogramm)"

# Modelle: Name -> (Architektur, Gewichte, Beschreibung)
MODELLE = {
    "mehrsprachig": ("xlm-roberta-base-ViT-B-32", "laion5b_s13b_b90k",
                     "Mehrsprachig (deutsche Beschreibungen möglich), ca. 1.1 GB"),
    "englisch":     ("ViT-B-32", "laion2b_s34b_b79k",
                     "Nur Englisch, kleiner und schneller, ca. 600 MB"),
    "englisch_gross": ("ViT-L-14", "laion2b_s32b_b82k",
                       "Nur Englisch, genauer, ca. 1.7 GB, 4x langsamer"),
}

STANDARD_KATEGORIEN = {
    "Hausumbau": [
        "Baustelle beim Umbau eines Hauses",
        "Gebäude mit Baugerüst",
        "unfertiger Raum im Rohbau mit nackten Wänden und Baumaterial",
        "Handwerker oder Werkzeug in einem Haus",
        "Baugrube, Schalung oder Fundament aus Beton",
        "Kabel, Rohre oder Dämmung während einer Renovation",
        "Dach oder Fassade im Bau",
    ],
    "Haus_fertig": ["fertig eingerichtetes Zimmer", "Haus mit Garten von aussen", "Küche oder Badezimmer"],
    "Landschaft": ["Landschaft mit Bergen, See oder Feldern", "Wanderweg in der Natur", "Sonnenuntergang"],
    "Tiere": ["Pferd", "Hund oder Katze", "Wildtier oder Vogel", "Kühe oder Schafe auf der Weide"],
    "Personen": ["Menschen, die für die Kamera posieren", "Porträt einer Person", "Gruppe von Leuten an einem Fest"],
    "Stadt_Gebaeude": ["Strasse in einer Stadt mit Häusern", "historisches Gebäude oder Kirche", "Flughafen oder Industrieanlage"],
    "Fahrzeuge_Maschinen": ["Auto, Lastwagen oder Motorrad", "Bagger oder Kran", "Flugzeug"],
    "Dokumente_Screenshots": ["Bildschirmfoto eines Computers oder Handys", "fotografiertes Dokument, Plan oder Zeichnung"],
    "Essen": ["Essen auf einem Teller", "Restauranttisch mit Getränken"],
}

STANDARD_EINSTELLUNGEN = {
    "quelle": "", "ziel": "",
    "nach_datum": True, "nach_ort": True, "nach_thema": False, "panorama": True,
    "datum_struktur": "Jahr/Jahr-Monat",      # oder "Jahr/Jahr-Monat-Tag", "Jahr-Monat"
    "verschieben": False, "testlaufe": True,
    "modell": "mehrsprachig", "schwelle": 0.45, "panorama_verhaeltnis": 2.0,
    "mehrfach": False,                # Bild zusätzlich in weitere Themen kopieren (z. B. Tier UND Hausumbau)
    "mehrfach_schwelle": 0.25,        # ab dieser Sicherheit zählt ein weiteres Thema mit
    "raster": 2, "kategorien": STANDARD_KATEGORIEN,
    "ausschluss": "._DAV, [Originaldateien], @eaDir, .thumbnails",   # Unterordner, die übersprungen werden
    "doppel_erkennen": True,          # doppelte / sehr ähnliche Bilder aussortieren
    "doppel_aehnlichkeit": 90,        # Prozent (100 = nur identische Bilder)
    "doppel_ordner": "",              # leer = <Ziel>/Aussortierte_Doppelbilder
}


# ---------------------------------------------------------------------------
# Update-Prüfung über GitHub (Pull: das Programm holt sich neue Versionen selbst)
# ---------------------------------------------------------------------------
# Adresse der Datei version.json im GitHub-Repository (raw-Adresse). In einstellungen.json
# kann sie mit "update_url" überschrieben werden.
UPDATE_URL = "https://raw.githubusercontent.com/silur25/fotosortierprogramm/main/version.json"
UPDATE_ZEITLIMIT = 4          # Sekunden für die Abfrage
UPDATE_INTERVALL_H = 24       # höchstens einmal pro Tag automatisch prüfen


def version_tupel(text: str):
    """'2.21.1' -> (2, 21, 1); ungültig -> (0,)"""
    m = re.search(r"(\d+(?:\.\d+)*)", str(text))
    if not m:
        return (0,)
    t = [int(x) for x in m.group(1).split(".")]
    return tuple(t + [0] * (3 - len(t)))


def update_pruefen(aktuelle_version: str, url: str = None):
    """
    Liest version.json. Rückgabe: dict mit 'version', 'hinweise', 'dateien' [{name, url, sha256}]
    wenn eine neuere Version vorliegt, sonst None. Bei Netzproblemen: None (stumm).
    """
    if not REQUESTS_OK:
        return None
    try:
        r = requests.get(url or UPDATE_URL, timeout=UPDATE_ZEITLIMIT,
                         headers={"Cache-Control": "no-cache", "User-Agent": USER_AGENT})
        if r.status_code != 200:
            return None
        info = r.json()
        if version_tupel(info.get("version", "0")) > version_tupel(aktuelle_version):
            return info
    except Exception:
        pass
    return None


def update_installieren(info: dict, programmordner: Path, log=print):
    """
    Lädt alle Dateien aus info['dateien'] herunter, prüft SHA-256 und ersetzt sie im Programmordner.
    Alte Programmversionen (Fotosortierprogramm_v*.pyw) werden anschliessend entfernt.
    Rückgabe: (ok: bool, meldung: str)
    """
    import hashlib
    import tempfile
    dateien = info.get("dateien", [])
    if not dateien:
        return False, "version.json enthält keine Dateien."
    tmp = Path(tempfile.mkdtemp(prefix="fotosortieren_update_"))
    geladen = []
    for d in dateien:
        name, url, soll = d.get("name"), d.get("url"), (d.get("sha256") or "").lower()
        if not name or not url or "/" in name or "\\" in name:
            return False, f"Ungültiger Eintrag in version.json: {d}"
        log(f"Lade {name} ...")
        try:
            r = requests.get(url, timeout=60, headers={"User-Agent": USER_AGENT})
            if r.status_code != 200:
                return False, f"Download fehlgeschlagen ({r.status_code}): {name}"
            daten = r.content
        except Exception as ex:
            return False, f"Download fehlgeschlagen: {name} ({ex})"
        ist = hashlib.sha256(daten).hexdigest()
        if soll and ist != soll:
            return False, f"Prüfsumme stimmt nicht: {name} – Update abgebrochen (Datei manipuliert oder unvollständig)."
        (tmp / name).write_bytes(daten)
        geladen.append(name)
    # erst nach vollständigem, geprüftem Download in den Programmordner kopieren
    for name in geladen:
        shutil.copy2(tmp / name, programmordner / name)
    neu = version_tupel(info.get("version", "0"))
    for alt in programmordner.glob("Fotosortierprogramm_v*.pyw"):
        if version_tupel(alt.stem.split("_v", 1)[-1]) < neu:
            try:
                alt.unlink()
            except Exception:
                pass
    shutil.rmtree(tmp, ignore_errors=True)
    return True, f"Version {info.get('version')} installiert: " + ", ".join(geladen)


# ---------------------------------------------------------------------------
# EXIF
# ---------------------------------------------------------------------------
def _rational(v):
    try:
        return float(v)
    except TypeError:
        return float(v[0]) / float(v[1])


def _gps_to_deg(dms, ref):
    d, m, s = (_rational(x) for x in dms)
    w = d + m / 60.0 + s / 3600.0
    return -w if ref in ("S", "W") else w


def exif_lesen(img: Image.Image):
    """(datum|None, (lat, lon)|None) aus einem geöffneten Bild."""
    datum, gps = None, None
    try:
        exif = img.getexif()
        if not exif:
            return None, None
        roh = None
        try:
            ifd = exif.get_ifd(ExifTags.IFD.Exif)
            roh = ifd.get(36867) or ifd.get(36868)
        except Exception:
            pass
        if not roh:
            roh = exif.get(36867) or exif.get(306)
        if roh:
            roh = str(roh).strip()
            for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y:%m:%d"):
                try:
                    datum = datetime.strptime(roh[:19], fmt)
                    break
                except ValueError:
                    continue
        try:
            g = exif.get_ifd(ExifTags.IFD.GPSInfo)
        except Exception:
            g = exif.get(34853)
        if g and 2 in g and 4 in g:
            lat = _gps_to_deg(g[2], g.get(1, "N"))
            lon = _gps_to_deg(g[4], g.get(3, "E"))
            if lat or lon:
                gps = (round(lat, 6), round(lon, 6))
    except Exception:
        pass
    return datum, gps


def bild_hash(img: Image.Image):
    """
    Bildsignatur für Ähnlichkeitsvergleich:
      - dHash waagrecht + senkrecht (128 Bit, Struktur/Kanten)
      - 4x4-Raster der mittleren Helligkeit (Helligkeitsverteilung)
    Damit werden auch detailarme Bilder (Wände, Himmel) korrekt unterschieden.
    """
    g = img.convert("L")
    a = g.resize((9, 8), Image.Resampling.LANCZOS)
    b = g.resize((8, 9), Image.Resampling.LANCZOS)
    pa, pb = list(a.getdata()), list(b.getdata())
    bits = 0
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if pa[y * 9 + x] > pa[y * 9 + x + 1] else 0)
    for y in range(8):
        for x in range(8):
            bits = (bits << 1) | (1 if pb[y * 8 + x] > pb[(y + 1) * 8 + x] else 0)
    raster = list(g.resize((4, 4), Image.Resampling.BOX).getdata())
    return bits, raster


def aehnlichkeit(s1, s2) -> float:
    """Ähnlichkeit zweier Signaturen in Prozent (100 = identisch)."""
    (h1, r1), (h2, r2) = s1, s2
    struktur = 100.0 * (128 - bin(h1 ^ h2).count("1")) / 128.0
    diff = sum(abs(x - y) for x, y in zip(r1, r2)) / len(r1)      # 0..255
    helligkeit = max(0.0, 100.0 * (1.0 - diff / 96.0))           # ab 96 Graustufen Differenz = 0 %
    return min(struktur, helligkeit)


class Doppelfinder:
    """Merkt sich Hashes bereits gesehener Bilder und findet Duplikate / sehr ähnliche Bilder."""

    def __init__(self, schwelle_prozent: float):
        self.schwelle = float(schwelle_prozent)
        self.gesehen = []          # [(signatur, pfad)]

    def pruefen(self, h: int, pfad: Path):
        """Gibt (original_pfad, aehnlichkeit) zurück, wenn ein ähnliches Bild schon gesehen wurde, sonst None."""
        best, best_a = None, 0.0
        for h0, p0 in self.gesehen:
            a = aehnlichkeit(h, h0)
            if a >= self.schwelle and a > best_a:
                best, best_a = p0, a
                if a >= 100.0:
                    break
        if best is None:
            self.gesehen.append((h, pfad))
            return None
        return best, best_a


# ---------------------------------------------------------------------------
# Geocoder (OpenStreetMap / Nominatim)
# ---------------------------------------------------------------------------
class Geocoder:
    def __init__(self, cache_datei: Path, raster: int, log):
        self.cache_datei, self.raster, self.log = cache_datei, raster, log
        self.cache, self.letzte, self.fehler = {}, 0.0, 0
        if cache_datei.exists():
            try:
                self.cache = json.loads(cache_datei.read_text(encoding="utf-8"))
            except Exception:
                pass

    def speichern(self):
        try:
            self.cache_datei.parent.mkdir(parents=True, exist_ok=True)
            self.cache_datei.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def adresse_auswerten(antwort: dict):
        a = antwort.get("address", {})
        land = a.get("country") or "Unbekannt"
        ort = (a.get("city") or a.get("town") or a.get("village") or a.get("municipality")
               or a.get("hamlet") or a.get("county") or a.get("state") or "Unbekannt")
        return land, ort

    def ort(self, lat, lon):
        key = f"{round(lat, self.raster)},{round(lon, self.raster)}"
        if key in self.cache:
            return tuple(self.cache[key])
        ergebnis = ("Unbekannt", key.replace(",", "_"))
        if not REQUESTS_OK:
            return ergebnis
        warte = 1.1 - (time.time() - self.letzte)
        if warte > 0:
            time.sleep(warte)
        try:
            r = requests.get(NOMINATIM_URL, params={"lat": lat, "lon": lon, "format": "jsonv2",
                                                    "zoom": 10, "accept-language": "de"},
                             headers={"User-Agent": USER_AGENT}, timeout=15)
            self.letzte = time.time()
            if r.status_code == 200:
                ergebnis = self.adresse_auswerten(r.json())
                self.cache[key] = list(ergebnis)
            else:
                self.fehler += 1
        except Exception as e:
            self.fehler += 1
            if self.fehler == 1:
                self.log(f"WARNUNG: Ortsabfrage fehlgeschlagen ({type(e).__name__}). Internet prüfen. "
                         "Betroffene Bilder landen unter nach_Ort/Unbekannt/<Koordinaten>.")
        return ergebnis


# ---------------------------------------------------------------------------
# Übersetzer Deutsch -> Englisch (lokal, für die englischen KI-Modelle)
# ---------------------------------------------------------------------------
UEBERSETZUNGS_MODELL = "Helsinki-NLP/opus-mt-de-en"
_ENGLISCH_MARKER = {"a", "an", "the", "of", "with", "and", "or", "in", "on", "at", "photo", "picture",
                    "house", "building", "people", "person", "street", "car", "dog", "cat", "horse", "under",
                    "room", "kitchen", "garden", "site", "construction", "landscape", "mountain", "animal"}
_DEUTSCH_MARKER = {"der", "die", "das", "ein", "eine", "einem", "einer", "eines", "mit", "und", "oder", "im",
                   "am", "auf", "von", "bei", "aus", "für", "nach", "über", "unter", "vor", "zum", "zur", "in",
                   "haus", "bild", "foto", "mensch", "menschen", "strasse", "gebäude", "garten", "zimmer", "küche",
                   "baustelle", "landschaft", "tier", "berg", "berge", "person", "personen", "leute", "wasser"}


def wirkt_deutsch(text: str) -> bool:
    """
    Entscheidet, ob eine Beschreibung übersetzt werden soll. Umlaute oder «ß» = deutsch.
    Sonst zählen deutsche gegen englische Signalwörter; nur wenn eindeutig mehr englische
    Signalwörter vorkommen, bleibt der Text unverändert. Mit «en:» markierte Zeilen nie übersetzen.
    """
    t = text.lower()
    if t.strip().startswith("en:"):
        return False
    if any(c in t for c in "äöüß"):
        return True
    woerter = re.findall(r"[a-z]+", t)
    de = sum(1 for w in woerter if w in _DEUTSCH_MARKER)
    en = sum(1 for w in woerter if w in _ENGLISCH_MARKER and w not in _DEUTSCH_MARKER)
    return not (en > de)


class Uebersetzer:
    """Übersetzt Themenbeschreibungen Deutsch -> Englisch; Ergebnisse werden in einer Datei gemerkt."""

    def __init__(self, cache_datei: Path, log):
        self.cache_datei, self.log = cache_datei, log
        self.cache = {}
        self.modell = self.tok = None
        self.fehler = None
        if cache_datei.exists():
            try:
                self.cache = json.loads(cache_datei.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _laden(self):
        if self.modell is not None or self.fehler:
            return
        try:
            from transformers import MarianMTModel, MarianTokenizer
            self.log(f"Lade Übersetzungsmodell {UEBERSETZUNGS_MODELL} (einmalig ca. 300 MB Download) ...")
            self.tok = MarianTokenizer.from_pretrained(UEBERSETZUNGS_MODELL)
            self.modell = MarianMTModel.from_pretrained(UEBERSETZUNGS_MODELL)
            self.modell.eval()
        except Exception as ex:
            self.fehler = f"{type(ex).__name__}: {ex}"
            self.log(f"WARNUNG: Übersetzungsmodell nicht verfügbar ({self.fehler}). "
                     "Deutsche Beschreibungen werden unübersetzt verwendet – Erkennung dadurch schlechter.")

    def uebersetzen(self, texte):
        """Liste deutscher Texte -> Liste englischer Texte (gleiche Reihenfolge)."""
        ergebnis = list(texte)
        offen = [(i, t) for i, t in enumerate(texte)
                 if t.strip().lower().startswith("en:") is False and wirkt_deutsch(t) and t not in self.cache]
        for i, t in enumerate(texte):
            if t.strip().lower().startswith("en:"):
                ergebnis[i] = t.strip()[3:].strip()        # "en: ..." = bereits englisch
            elif t in self.cache:
                ergebnis[i] = self.cache[t]
            elif not wirkt_deutsch(t):
                ergebnis[i] = t                             # wirkt englisch -> unverändert
        if offen:
            self._laden()
            if self.modell is not None:
                import torch
                saetze = [t for _, t in offen]
                with torch.no_grad():
                    eing = self.tok(saetze, return_tensors="pt", padding=True, truncation=True)
                    aus = self.modell.generate(**eing, max_new_tokens=64, num_beams=2)
                uebers = self.tok.batch_decode(aus, skip_special_tokens=True)
                for (i, t), u in zip(offen, uebers):
                    u = u.strip().rstrip(".")
                    self.cache[t] = u
                    ergebnis[i] = u
                try:
                    self.cache_datei.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")
                except Exception:
                    pass
        return ergebnis


# ---------------------------------------------------------------------------
# Themen-Klassifikator (CLIP, lokal)
# ---------------------------------------------------------------------------
class Klassifikator:
    def __init__(self, modell: str, kategorien: dict, log, ohne_gewichte=False, uebersetzer=None):
        import torch
        import open_clip
        self.torch = torch
        arch, gewichte, _ = MODELLE[modell]
        self.geraet = "cuda" if torch.cuda.is_available() else "cpu"
        log(f"Lade KI-Modell {arch} auf {self.geraet.upper()} (beim ersten Mal Download, bitte warten) ...")
        self.modell, _, self.vorverarbeitung = open_clip.create_model_and_transforms(
            arch, pretrained=None if ohne_gewichte else gewichte, device=self.geraet)
        self.modell.eval()
        tok = open_clip.get_tokenizer(arch)
        self.namen = [k for k, v in kategorien.items() if v]
        self.verwendet = {}                     # Thema -> tatsächlich verwendete Beschreibungen
        embs = []
        with torch.no_grad():
            for name in self.namen:
                beschr = list(kategorien[name])
                if modell != "mehrsprachig" and uebersetzer is not None:
                    beschr = uebersetzer.uebersetzen(beschr)
                    saetze = [b if b.lower().startswith(("a ", "an ", "the ")) else f"a photo of {b}" for b in beschr]
                else:
                    saetze = [f"ein Foto von {b}" if not b.lower().startswith(("ein ", "eine ", "a ")) else b
                              for b in beschr]
                self.verwendet[name] = beschr
                e = self.modell.encode_text(tok(saetze).to(self.geraet))
                e = e / e.norm(dim=-1, keepdim=True)
                e = e.mean(dim=0)
                embs.append(e / e.norm())
        self.text_emb = torch.stack(embs)
        log(f"Modell bereit. Kategorien: {', '.join(self.namen)}")
        if modell != "mehrsprachig" and uebersetzer is not None:
            for name in self.namen:
                log(f"   {name}: " + "; ".join(self.verwendet[name]))

    def bewerten(self, img: Image.Image):
        x = self.vorverarbeitung(img.convert("RGB")).unsqueeze(0).to(self.geraet)
        with self.torch.no_grad():
            e = self.modell.encode_image(x)
            e = e / e.norm(dim=-1, keepdim=True)
            p = (100.0 * e @ self.text_emb.T).softmax(dim=-1)[0].tolist()
        return sorted(zip(self.namen, p), key=lambda t: t[1], reverse=True)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------
def sicherer_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(s)).strip(" .")
    return s or "Unbekannt"


NETZ_FEHLER = {53, 59, 64, 121, 1231, 1232, 1265}     # Windows-Fehlercodes für Netzwerkunterbruch (WinError)
NETZ_VERSUCHE = 4                                    # Wiederholungen bei Netzfehler
NETZ_PAUSE = 8                                       # Sekunden Pause zwischen den Versuchen


def ist_netzfehler(ex: Exception) -> bool:
    w = getattr(ex, "winerror", None)
    return w in NETZ_FEHLER or ("Netzwerk" in str(ex)) or ("network" in str(ex).lower())


def mit_wiederholung(fn, log=None, was=""):
    """Führt fn() aus; bei Netzwerkfehlern bis zu NETZ_VERSUCHE Mal mit Pause wiederholen."""
    for versuch in range(1, NETZ_VERSUCHE + 1):
        try:
            return fn()
        except OSError as ex:
            if not ist_netzfehler(ex) or versuch == NETZ_VERSUCHE:
                raise
            if log:
                log(f"   Netzwerkfehler bei {was} ({ex}). Warte {NETZ_PAUSE} s und versuche erneut "
                    f"({versuch}/{NETZ_VERSUCHE - 1}) ...")
            time.sleep(NETZ_PAUSE)


def _lang(p: Path) -> str:
    """Windows: Pfade über 240 Zeichen mit \\\\?\\-Präfix, damit Kopieren nicht an der 260-Zeichen-Grenze scheitert."""
    sp = str(p)
    if len(sp) > 240 and sp[1:3] == ":\\" and not sp.startswith("\\\\?\\"):
        return "\\\\?\\" + sp
    return sp


def ziel_frei(ziel: Path, quelle: Path):
    """Freier Zielpfad oder None, wenn dieselbe Datei (Name + Grösse) schon dort liegt."""
    if not ziel.exists():
        return ziel
    if ziel.stat().st_size == quelle.stat().st_size:
        return None
    i = 1
    while True:
        k = ziel.with_name(f"{ziel.stem}_{i}{ziel.suffix}")
        if not k.exists():
            return k
        i += 1


def datums_ordner(basis: Path, datum: datetime, struktur: str, sicher: bool) -> Path:
    if struktur == "Jahr/Jahr-Monat-Tag":
        o = basis / f"{datum:%Y}" / f"{datum:%Y-%m-%d}"
    elif struktur == "Jahr-Monat":
        o = basis / f"{datum:%Y-%m}"
    else:
        o = basis / f"{datum:%Y}" / f"{datum:%Y-%m}"
    return o if sicher else o / "_ohne_EXIF-Datum"


def einstellungen_laden(pfad: Path) -> dict:
    e = json.loads(json.dumps(STANDARD_EINSTELLUNGEN))
    if pfad.exists():
        try:
            e.update(json.loads(pfad.read_text(encoding="utf-8")))
        except Exception:
            pass
    return e


def einstellungen_speichern(pfad: Path, e: dict):
    pfad.write_text(json.dumps(e, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Hauptlauf
# ---------------------------------------------------------------------------
class Sortierlauf:
    """
    e         : Einstellungen (dict, siehe STANDARD_EINSTELLUNGEN)
    log(text) : Callback für Meldungen
    fortschritt(n, total) : Callback
    abbruch   : threading.Event – wird gesetzt, wenn der Nutzer abbricht
    """

    def __init__(self, e: dict, log=print, fortschritt=None, abbruch=None, ohne_gewichte=False):
        self.e, self.log = e, log
        self.fortschritt = fortschritt or (lambda n, t: None)
        self.abbruch = abbruch or threading.Event()
        self.ohne_gewichte = ohne_gewichte
        self.netz_abbruch = False

    def pruefen(self):
        quelle = Path(self.e["quelle"]).expanduser()
        ziel = Path(self.e["ziel"]).expanduser()
        if not quelle.is_dir():
            return f"Quellordner nicht gefunden: {quelle}"
        if not str(ziel).strip():
            return "Bitte einen Zielordner wählen."
        qr, zr = quelle.resolve(), ziel.resolve()
        if zr == qr or qr in zr.parents:
            return "Der Zielordner darf nicht innerhalb des Quellordners liegen."
        if not (self.e["nach_datum"] or self.e["nach_ort"] or self.e["nach_thema"]):
            return "Mindestens eine Sortierart (Datum, Ort, Thema) wählen."
        if self.e["nach_thema"]:
            try:
                import torch, open_clip  # noqa
                if self.e["modell"] == "mehrsprachig":
                    import transformers, sentencepiece  # noqa
            except ImportError as ex:
                return (f"Für die Themensortierung fehlt das Modul «{ex.name}».\n"
                        "Bitte installieren.bat ausführen oder:\n"
                        "pip install torch open_clip_torch transformers sentencepiece")
        return None

    def starten(self):
        e = self.e
        quelle = Path(e["quelle"]).expanduser().resolve()
        ziel = Path(e["ziel"]).expanduser().resolve()
        testlauf = bool(e["testlaufe"])
        verschieben = bool(e["verschieben"]) and not testlauf
        log = self.log

        if not testlauf:
            ziel.mkdir(parents=True, exist_ok=True)
        log(f"Quelle: {quelle}\nZiel:   {ziel}")
        if testlauf:
            log("TESTLAUF – es wird nichts kopiert oder verschoben.")
        if not HEIF_OK:
            log("Hinweis: pillow-heif fehlt – HEIC-Bilder (iPhone) erhalten nur das Dateidatum.")

        geo = kl = None
        doppel = None
        if e.get("doppel_erkennen"):
            doppel = Doppelfinder(float(e.get("doppel_aehnlichkeit", 90)))
            do = str(e.get("doppel_ordner", "")).strip()
            doppel_ordner = Path(do).expanduser().resolve() if do else ziel / "Aussortierte_Doppelbilder"
            log(f"Doppelbilder: ab {doppel.schwelle:.0f} % Ähnlichkeit -> {doppel_ordner}")
        if e["nach_ort"]:
            cache = (ziel if not testlauf else Path(e.get("_programmordner", ziel))) / "geocache.json"
            geo = Geocoder(cache, int(e["raster"]), log)
            if not REQUESTS_OK:
                log("Hinweis: Modul requests fehlt – Ortsordner erhalten nur Koordinaten.")
        if e["nach_thema"]:
            try:
                ueb = None
                if e["modell"] != "mehrsprachig":
                    ueb = Uebersetzer(Path(e.get("_programmordner", ziel)) / "uebersetzungen.json", log)
                    log("Englisches KI-Modell gewählt: deutsche Themenbeschreibungen werden automatisch übersetzt.")
                kl = Klassifikator(e["modell"], e["kategorien"], log, self.ohne_gewichte, ueb)
                if e.get("mehrfach"):
                    log(f"Mehrfachzuordnung: Bilder werden zusätzlich in jedes weitere Thema kopiert, "
                        f"das mindestens {float(e.get('mehrfach_schwelle', 0.25)):.2f} Sicherheit erreicht.")
            except Exception as ex:
                log(f"FEHLER beim Laden des KI-Modells: {ex}\nThemensortierung wird übersprungen.")
                kl = None

        ausschluss = {a.strip().lower() for a in str(e.get("ausschluss", "")).split(",") if a.strip()}

        def ausgeschlossen(f: Path):
            return any(teil.lower() in ausschluss for teil in f.relative_to(quelle).parts[:-1])

        alle = [f for f in quelle.rglob("*") if f.is_file() and f.suffix.lower() in BILD_ENDUNGEN | VIDEO_ENDUNGEN]
        dateien = sorted(f for f in alle if not ausgeschlossen(f))
        total = len(dateien)
        log(f"{total} Dateien gefunden" + (f", {len(alle) - total} in ausgeschlossenen Unterordnern übersprungen"
                                            if len(alle) != total else "") + ".\n")
        protokoll, zaehler = [], {}

        def zaehle(k):
            zaehler[k] = zaehler.get(k, 0) + 1

        def uebertragen(f: Path, z: Path, move: bool) -> str:
            zz = ziel_frei(z, f)
            if zz is None:
                zaehle("übersprungen (existiert bereits)")
                return "übersprungen"
            if not testlauf:
                zz.parent.mkdir(parents=True, exist_ok=True)
                if move:
                    mit_wiederholung(lambda: shutil.move(_lang(f), _lang(zz)), log, f.name)
                else:
                    mit_wiederholung(lambda: shutil.copy2(_lang(f), _lang(zz)), log, f.name)
            return str(zz.relative_to(ziel))

        netzfehler_folge = 0
        netz_abbruch = False
        for n, f in enumerate(dateien, 1):
            if self.abbruch.is_set():
                if not netz_abbruch:
                    log("\nAbgebrochen durch Benutzer.")
                break
            self.fortschritt(n, total)
            try:
                zeile = {"Nr": n, "Quelle": str(f), "Datum": "", "Datumsquelle": "", "Lat": "", "Lon": "",
                         "Land": "", "Ort": "", "Kategorie": "", "Sicherheit": "", "Zweite_Wahl": "",
                         "Weitere_Themen": "",
                         "Panorama": "", "Ziel_Datum": "", "Ziel_Ort": "", "Ziel_Thema": "",
                         "Doppelbild": "", "Doppelbild_von": "", "Aehnlichkeit": "", "Ziel_Doppel": ""}
                datum = gps = None
                bewertung, panorama = None, False
                treffer = None
                ist_bild = f.suffix.lower() in BILD_ENDUNGEN
                if ist_bild:
                    try:
                        with Image.open(f) as img:
                            datum, gps = exif_lesen(img)
                            b, h = img.size
                            panorama = bool(h) and (b / h) >= float(e["panorama_verhaeltnis"])
                            if doppel is not None:
                                treffer = doppel.pruefen(bild_hash(img), f)
                            if kl is not None and treffer is None:
                                bewertung = kl.bewerten(img)
                    except Exception as ex:
                        log(f"[{n}/{total}] {f.name}: FEHLER beim Lesen ({ex})")
                        zaehle("Fehler")
                        zeile["Datumsquelle"] = f"FEHLER {ex}"
                        protokoll.append(zeile)
                        continue
                if datum:
                    dq = "EXIF"
                else:
                    datum = datetime.fromtimestamp(f.stat().st_mtime)
                    dq = "Dateidatum"
                zeile.update(Datum=datum.strftime("%Y-%m-%d %H:%M:%S"), Datumsquelle=dq)
                meldung = [f"{datum:%Y-%m-%d} ({dq})"]

                # Doppelbild: nur in den Doppelbilder-Ordner, nicht in die Sortierstrukturen
                if treffer is not None:
                    orig, a = treffer
                    zeile.update(Doppelbild="ja", Doppelbild_von=str(orig), Aehnlichkeit=f"{a:.0f}")
                    zz = ziel_frei(doppel_ordner / f.name, f)
                    if zz is None:
                        zeile["Ziel_Doppel"] = "übersprungen"
                    else:
                        if not testlauf:
                            zz.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copy2(f, zz)
                        zeile["Ziel_Doppel"] = str(zz)
                    zaehle("Doppelbild aussortiert")
                    protokoll.append(zeile)
                    log(f"[{n}/{total}] {f.name}: DOPPELBILD ({a:.0f} % wie {orig.name}) -> Aussortierte Doppelbilder")
                    continue

                # Ort (vor dem allfälligen Verschieben)
                if gps:
                    zeile.update(Lat=gps[0], Lon=gps[1])
                    if geo is not None:
                        land, ort = geo.ort(*gps)
                        zeile.update(Land=land, Ort=ort)
                        zeile["Ziel_Ort"] = uebertragen(
                            f, ziel / "nach_Ort" / sicherer_name(land) / sicherer_name(ort) / f.name, False)
                        zaehle(f"Ort: {land}/{ort}")
                        meldung.append(f"{land}/{ort}")

                # Thema
                if kl is not None and bewertung:
                    (k1, p1), (k2, p2) = bewertung[0], (bewertung[1] if len(bewertung) > 1 else ("", 0.0))
                    kat = k1 if p1 >= float(e["schwelle"]) else "_unsicher"
                    zeile.update(Kategorie=kat, Sicherheit=f"{p1:.2f}", Zweite_Wahl=f"{k2} ({p2:.2f})")
                    zeile["Ziel_Thema"] = uebertragen(f, ziel / "nach_Thema" / sicherer_name(kat) / f.name, False)
                    zaehle(f"Thema: {kat}")
                    meldung.append(f"{kat} {p1:.0%}")
                    # Mehrfachzuordnung: weitere Themen ab der zweiten Schwelle (nur wenn das Hauptthema sicher ist)
                    if e.get("mehrfach") and kat != "_unsicher":
                        ms = float(e.get("mehrfach_schwelle", 0.25))
                        weitere = [(k, p) for k, p in bewertung[1:] if p >= ms]
                        if weitere:
                            zeile["Weitere_Themen"] = ", ".join(f"{k} ({p:.2f})" for k, p in weitere)
                            for k, p in weitere:
                                z = uebertragen(f, ziel / "nach_Thema" / sicherer_name(k) / f.name, False)
                                zeile["Ziel_Thema"] += " | " + z
                                zaehle(f"Thema: {k} (zusätzlich)")
                                meldung.append(f"+ {k} {p:.0%}")
                if e["panorama"] and panorama and ist_bild:
                    zeile["Panorama"] = "ja"
                    z = uebertragen(f, ziel / "nach_Thema" / "Panorama" / f.name, False)
                    zeile["Ziel_Thema"] = (zeile["Ziel_Thema"] + " | " if zeile["Ziel_Thema"] else "") + z
                    zaehle("Thema: Panorama")
                    meldung.append("Panorama")

                # Datum zuletzt (bei «verschieben» ist die Quelle danach weg)
                if e["nach_datum"]:
                    o = datums_ordner(ziel / "nach_Datum", datum, e["datum_struktur"], dq == "EXIF")
                    zeile["Ziel_Datum"] = uebertragen(f, o / f.name, verschieben)
                    zaehle("Datum: " + ("aus EXIF" if dq == "EXIF" else "aus Dateidatum (_ohne_EXIF-Datum)"))

                protokoll.append(zeile)
                log(f"[{n}/{total}] {f.name}: " + ", ".join(meldung))
                if geo is not None and n % 25 == 0:
                    geo.speichern()
            except Exception as ex:
                fehler_text = f"{type(ex).__name__}: {ex}"
                zeile["Datumsquelle"] = "FEHLER"
                zeile["Ziel_Datum"] = fehler_text
                protokoll.append(zeile)
                zaehle("Fehler (Datei übersprungen)")
                log(f"[{n}/{total}] {f.name}: FEHLER – Datei übersprungen ({fehler_text})")
                if ist_netzfehler(ex):
                    netzfehler_folge += 1
                    if netzfehler_folge >= 3:
                        log("\nNETZWERK UNTERBROCHEN: Die Verbindung zum Quell- oder Zielordner ist weg "
                            "(z. B. NAS/Tailscale). Lauf wird gestoppt.\n"
                            "Verbindung prüfen und den Lauf erneut starten – bei der Frage nach früheren "
                            "Ergebnissen NEIN (behalten und ergänzen) wählen; bereits kopierte Dateien werden "
                            "übersprungen.")
                        self.abbruch.set()
                        netz_abbruch = True
                        self.netz_abbruch = True
                else:
                    netzfehler_folge = 0
                continue
            netzfehler_folge = 0

        if geo is not None:
            geo.speichern()

        # Liste der Doppelbilder in den Doppelbilder-Ordner
        dz = [z for z in protokoll if z.get("Doppelbild") == "ja"]
        if doppel is not None and dz and not testlauf:
            try:
                doppel_ordner.mkdir(parents=True, exist_ok=True)
                with open(doppel_ordner / "Doppelbilder_Liste.txt", "a", encoding="utf-8") as fh:
                    fh.write(f"\n--- Lauf {datetime.now():%Y-%m-%d %H:%M} ---\n")
                    for z in dz:
                        fh.write(f"{Path(z['Quelle']).name}  ({z['Aehnlichkeit']} %)  = Doppel von  {z['Doppelbild_von']}\n")
            except Exception:
                pass

        # Protokoll
        basis = ziel if not testlauf else Path(e.get("_programmordner", quelle.parent))
        try:
            basis.mkdir(parents=True, exist_ok=True)
            pfad = basis / f"sortierprotokoll_{datetime.now():%Y%m%d_%H%M%S}.csv"
            with open(pfad, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.DictWriter(fh, fieldnames=list(protokoll[0].keys()) if protokoll else ["Nr"], delimiter=";")
                w.writeheader()
                w.writerows(protokoll)
            log(f"\nProtokoll (Excel): {pfad}")
        except Exception as ex:
            log(f"\nProtokoll konnte nicht geschrieben werden: {ex}")

        log("\nZusammenfassung")
        log(f"  Dateien total: {total}")
        for k, v in sorted(zaehler.items()):
            log(f"  {k}: {v}")
        if kl is not None:
            log("\nBilder unter nach_Thema/_unsicher und die Spalte «Zweite_Wahl» im Protokoll prüfen.")
        log("\nFERTIG." if not self.abbruch.is_set() else "")
        return protokoll, zaehler
