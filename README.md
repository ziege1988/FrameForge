# FrameForge

*Analyse. **Entscheide.** Perfektioniere.*

**Astrophotography Quality Analyzer** – FrameForge untersucht große Mengen astronomischer Rohbilder und Videos automatisch auf ihre technische Qualität, erstellt eine nachvollziehbare Rangliste und ermittelt die besten Frames für das Stacking.

> Nicht die Menge der Aufnahmen entscheidet, sondern die Qualität der Daten, aus denen das beste Ergebnis entsteht.

Desktop-Anwendung für **Windows und macOS**, vollständig lokal (kein Cloud-Upload), ausschließlich mit kostenfreien Werkzeugen gebaut.

---

## Funktionen

| Funktion | Umsetzung |
|---|---|
| Automatische Qualitätsanalyse | Schärfe, Kontrast, Rauschen/SNR, Belichtung & Clipping, Bildstabilität, Bewegungsunschärfe, lokale Qualität – je Frame |
| Intelligentes Ranking | Vergleich aller Dateien eines Ordners/einer Session, Score 0–100, Urteil *Empfohlen / Bedingt geeignet / Nicht empfohlen* |
| Transparente Entscheidungen | Jede Bewertung mit Teil-Scores, Begründungen (✓/✗) und konkreten Empfehlungen |
| Frame-Selektion | Qualität jedes Frames, empfohlener Stacking-Anteil, Export der besten Frames als neue **SER-Datei** (Originaldaten, unverändert) oder als CSV-Liste |
| Verarbeitungspotenzial | erwartetes Stack-SNR, Einstufung hoch / mittel / gering |
| Session-Vergleich & Qualitätsverlauf | Qualitätskurven mehrerer Videos übereinander, Seeing-Schwankung, Trend über die Session |
| Objektprofile | **Sonne**, **Mond**, **Planeten**, **Deep-Sky**, **Allgemein** – eigene Messgrößen, Gewichtung, Belichtungsziele |
| Übersicht-Dashboard | Empfehlungsquote, Ø-Qualitäts-Score mit Trend, Top-Ergebnisse, Ausschluss-Gründe, Vorschau mit Zoom |
| Projekte | komplette Analyse als `.ffproj` speichern und später ohne erneute Analyse öffnen |
| Effiziente Verarbeitung | Frames werden einzeln gelesen; eine 614-MB-SER-Datei (2000 Frames) wird mit ca. 80 MB RAM in ~6 s vollständig analysiert (Messung auf 4 Kernen) |
| Start-Popup mit Logo | Splash-Screen beim Programmstart, danach Willkommensdialog mit Schnellstart (abschaltbar) |
| Updates | Prüfung beim Start, Anzeige & Installation direkt in *Einstellungen › Updates* (SHA-256-geprüft) |

### Unterstützte Formate

| Format | Details |
|---|---|
| **SER** | 8/16 bit, Mono, Bayer, RGB/BGR, Zeitstempel; Byte-Reihenfolge wird aus dem Bildinhalt erkannt (das *LittleEndian*-Flag wird von Aufnahmeprogrammen uneinheitlich gesetzt) |
| **AVI, MP4, MOV, MKV** | über OpenCV/FFmpeg (z. B. Y800, MJPEG, H.264, unkomprimiert) |
| **FITS** | eigener schlanker Reader: Einzelbild, RGB-Würfel, Frame-Würfel, Bild-Extensions, BZERO/BSCALE, Bayer-Header (`BAYERPAT`). Komprimierte FITS (fpack) optional über *astropy* |
| **TIFF** | 8/16/32 bit, Mono/RGB, Multipage, LZW/ZIP-komprimiert |
| **RAW** | CR2, CR3, NEF, ARW, DNG, RAF, ORF, RW2, PEF u. a. über LibRaw (Bayer-Rohdaten, ohne Entwicklung) |
| PNG / JPEG / BMP | zusätzlich |

Farbdaten werden für die Messung in Luminanz umgerechnet; Bayer-Daten werden 2×2 zusammengefasst (kein Debayering → keine Interpolationsartefakte in den Messwerten).

---

## So bewertet FrameForge

**Pro Frame** (`frameforge/core/metrics.py`)

* **Objekterkennung**: Planetenscheibe → nur die Scheibe wird gemessen; Mond-/Sonnenoberfläche füllt das Bild → ganzes Feld.
* **Schärfe**: Standardabweichung des Laplace-gefilterten Bildes, ergänzt durch Gradientenenergie (Tenengrad), normiert auf die Helligkeit. Der Rauschanteil wird **analytisch abgezogen** (σ²·ΣK²), damit verrauschte Frames nicht fälschlich „scharf“ wirken.
* **Rauschen**: Immerkaer-Schätzer, nur im Objekt, Kanten ausgeschlossen.
* **Belichtung**: 99,5-%-Perzentil des Objekts, Anteil gesättigter und schwarzer Pixel.
* **Bewegungsunschärfe**: Anisotropie des Strukturtensors (gerichtete Unschärfe inkl. Richtung).
* **Lokale Qualität**: Schärfe je Kachel (3×3 bzw. 4×4), Planetenrand ausgeschlossen.
* **Bildstabilität**: Verschiebung zwischen Frames per Phasenkorrelation; lineare Drift (Nachführung) wird von der Bildunruhe getrennt.

**Deep-Sky** (`frameforge/core/deepsky.py`) – Kriterien wie bei gängigen Subframe-Selektoren:

* **FWHM** der Sterne (Seeing, Fokus) über Momente oberhalb von 20 % des Maximums, analytisch korrigiert (Abweichung < 5 % bei FWHM ≥ 2,5 px).
* **Exzentrizität** und Richtung (Nachführung, Wind, Verkippung); ab 0,7 wird abgelehnt.
* **Sternanzahl** (Transparenz) und **Himmelshintergrund** (Mond, Lichtverschmutzung, Wolken); weniger Sterne bei hellerem Hintergrund → Wolken/Dunst.
* **Bildfeld**: FWHM je Bildbereich (Verkippung, Bildfeldwölbung, Koma).
* Nebel und großflächige Gradienten werden vor der Sternsuche lokal abgezogen.
* Session-Hinweis bei steigender FWHM im Verlauf (Fokusdrift).

**Pro Datei / Session** (`frameforge/core/scoring.py`)

* Absolute Bewertung, wo es ein physikalisches Ziel gibt (Belichtung, Clipping, Stabilität, angeschnittenes Objekt).
* Relative Bewertung gegenüber dem **Session-Median**, wo nur ein Vergleich sinnvoll ist (Schärfe, Kontrast, Bewegungsunschärfe): `50 + 50·tanh(ln(Wert/Median)/Skala)`.
* Nicht beurteilbare Komponenten (z. B. Schärfe einer einzelnen Datei ohne Vergleich) werden **ausgelassen und offen benannt**, statt geraten.
* Stacking-Empfehlung: Anteil der Frames innerhalb von 20 % der Spitzenqualität, begrenzt auf 5–60 % und mindestens 50 Frames.

---

## Installation (Endanwender)

Installationspakete stehen unter **Releases** bereit:

* **Windows**: `FrameForge-<version>-windows-x64-setup.exe` – Installation pro Benutzer, keine Administratorrechte nötig.
* **macOS**: `FrameForge-<version>-macos-arm64.dmg` (Apple Silicon) bzw. `…-macos-x86_64.dmg` (Intel) – App in den Ordner *Programme* ziehen.

**Hinweis zur Signierung (kostenfreie Variante):** Die Pakete sind nicht mit kostenpflichtigen Zertifikaten signiert.

* Windows zeigt beim ersten Start ggf. *„Der Computer wurde durch Windows geschützt“* → *Weitere Informationen › Trotzdem ausführen*.
* macOS: beim ersten Öffnen *Systemeinstellungen › Datenschutz & Sicherheit › Trotzdem öffnen* (ältere Versionen: Rechtsklick › Öffnen).
* Spätere Updates über die App selbst benötigen diesen Schritt in der Regel nicht erneut.

---

## Bedienung

1. Im **Willkommensdialog** oder auf der **Übersicht** das Objekt wählen (Sonne, Mond, Planeten, Deep-Sky, Allgemein) und *Ordner analysieren* bzw. *Video analysieren* klicken – die Analyse startet sofort. Alternativ Dateien/Ordner ins Fenster ziehen.
2. Der **Modus** (Seite *Analyse* oder Menü *Analyse › Modus*):
   * *Schnell* – bis 200 Frames je Video, reduzierte Auflösung
   * *Standard* – bis 1000 Frames je Video
   * *Vollständig* – jeder Frame in voller Auflösung
3. **Übersicht**: Ergebnis-Dashboard mit Empfehlungsquote, Ø-Score, Top-Ergebnissen, Details, Ausschluss-Gründen, Empfehlungen und Vorschau. Doppelklick auf eine Datei öffnet sie in der Analyse.
4. **Analyse**: vollständige Tabelle (sortierbar) und je Datei **Bewertung**, **Qualitätsverlauf** (mehrere Dateien markieren = Session-Vergleich), **Vorschau** (bester Frame, Zoom, lokale Qualitätskarte) und **Frame-Selektion** (Export als SER/CSV).
5. **Rechenprotokoll** (Strg+L): seitliches Live-Panel, das jeden Rechenschritt mit den echten Werten zeigt – von der Objekterkennung über die Frame-Metriken bis zur Score-Formel.
6. **Berichte**: Export als CSV (Excel-kompatibel, `;`-getrennt) oder JSON, Projekt speichern/öffnen, Session-Zusammenfassung.

### Kommandozeile

```bash
frameforge analyze /pfad/zur/session --profile planet --mode standard --csv bericht.csv --json bericht.json
frameforge analyze jupiter_*.ser --export-best ./beste_frames
```

### Probleme & Protokoll

* *Hilfe › Problem melden …* öffnet ein vorausgefülltes GitHub-Issue (Version, System). Es wird nichts automatisch gesendet – du prüfst den Text vor dem Absenden.
* Bei unerwarteten Fehlern erscheint ein Dialog mit Details; Ursache und Analyseverlauf stehen im Protokoll (*Hilfe › Protokollordner öffnen*):
  Windows `%LOCALAPPDATA%\FrameForge\logs`, macOS `~/Library/Logs/FrameForge`.
* Doppelklick auf eine `.ffproj`-Datei öffnet das Projekt; SER/FITS lassen sich über *Öffnen mit › FrameForge* direkt analysieren.

---

## Entwicklung

Voraussetzung: Python ≥ 3.10 (Builds verwenden 3.12).

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q                 # Tests (Qt läuft headless)
python -m frameforge      # GUI starten
```

### Projektstruktur

```
frameforge/
  core/            Analyse ohne GUI-Abhängigkeit
    io/            Reader: ser.py, video.py, fits.py, tiff.py, raw.py, image.py, registry.py
    metrics.py     Frame-Metriken (Sonne, Mond, Planeten)
    deepsky.py     Stern-Metriken (FWHM, Exzentrizität, Sternanzahl, Hintergrund)
    project.py     Projekte (.ffproj) speichern/laden
    profiles.py    Objektprofile (Sonne, Mond, Planeten, Deep-Sky, Allgemein)
    scoring.py     Scores, Urteile, Begründungen, Empfehlungen
    analyzer.py    Datei-/Session-Analyse (Thread-Pool, Stichproben, Abbruch)
    export.py      CSV/JSON-Berichte, SER-Export der besten Frames
  gui/             PySide6-Oberfläche: app.py (Splash), welcome.py (Start-Popup), main_window.py,
                   dashboard.py (Übersicht), pages.py (Berichte, Info), settings_page.py, components.py, icons.py
  updater.py       Update-Prüfung, Download mit SHA-256-Prüfung, Installation
  cli.py           Kommandozeile
packaging/         PyInstaller-Spec, Icons, Inno-Setup-Skript (Windows), DMG-Skript (macOS)
.github/workflows/ ci.yml (Tests auf Windows/macOS/Linux), release.yml (Installer + Release)
tests/             pytest-Suite mit synthetischen Testdaten
```

### Release erstellen (löst auch die In-App-Updates aus)

1. Version in `frameforge/__init__.py` erhöhen und `CHANGELOG.md` ergänzen.
2. Commit pushen, dann auf GitHub *Actions › Release › Run workflow* mit Haken **„Release veröffentlichen“** starten (alternativ Tag pushen: `git tag v0.2.0 && git push origin v0.2.0`).
3. GitHub Actions baut Windows- und macOS-Installer, erzeugt `SHA256SUMS.txt` und veröffentlicht das Release. Tags mit Bindestrich (z. B. `v0.3.0-beta.1`) werden als Vorabversion markiert und nur angeboten, wenn *„Auch Vorabversionen anbieten“* aktiviert ist.

**Hinweise zur Build-Pipeline (kostenfreie Variante):** Für öffentliche Repositories sind die GitHub-Actions-Builds kostenlos. Release-Builds installieren nur fertige Binärpakete; fehlt für eine Plattform (z. B. Intel-Macs) ein Paket, schlägt nur dieser Build schnell fehl, die übrigen Pakete werden trotzdem veröffentlicht. Den Build kann man ohne Veröffentlichung testen: *Actions › Release › Run workflow*.

**Wichtig für Updates:** Die App fragt die GitHub-API ohne Anmeldung ab. Das funktioniert nur, wenn das Repository (bzw. das in `UPDATE_REPOSITORY` eingetragene Release-Repository) **öffentlich** ist. Bei einem privaten Repository kann ein separates öffentliches Repository nur für Releases verwendet werden.

### Erscheinungsbild

Unter *Einstellungen › Erscheinungsbild* lässt sich der Hintergrund wählen: ein erzeugter Sternenhimmel, mitgelieferte Astrofotos oder ein eigenes Bild. Die Oberflächenfarben werden automatisch aus dem dominanten Farbton der farbigen Bildbereiche abgeleitet (sättigungsgewichtetes Farbton-Histogramm), damit Menüs und Knöpfe zum Nebel passen.

**Bildrechte:** Die mitgelieferten Hintergrundfotos (`frameforge/resources/backgrounds/`) sind Aufnahmen des Repository-Inhabers. Sie dürfen nur zusammen mit FrameForge verwendet werden und fallen nicht unter die GPL des Codes.

---

## Lizenz

FrameForge ist freie Software unter der **GNU General Public License v3.0 oder neuer** (GPL-3.0-or-later), siehe [LICENSE](LICENSE).
Copyright © 2026 ziege1988.

* Nutzung, Weitergabe und Veränderung sind kostenlos erlaubt.
* Wer FrameForge (oder darauf aufbauende Programme) weitergibt, muss den Quellcode ebenfalls unter der GPL bereitstellen.
* Keine Gewährleistung (siehe Abschnitte 15–16 der Lizenz).

**Ausgenommen** sind die Hintergrundfotos in `frameforge/resources/backgrounds/` (eigene Aufnahmen des Repository-Inhabers, alle Rechte vorbehalten; Nutzung nur zusammen mit FrameForge).

## Lizenzhinweise der verwendeten Bibliotheken

Alle Abhängigkeiten sind kostenfrei: NumPy (BSD), OpenCV (Apache 2.0), PySide6/Qt (LGPLv3), tifffile (BSD), imagecodecs (BSD), rawpy (MIT) mit LibRaw (LGPL 2.1/CDDL), certifi (MPL 2.0), PyInstaller (GPL mit Ausnahme für gebündelte Programme), Inno Setup (kostenfrei). Bei der Weitergabe der gebündelten App sind die LGPL-Hinweise für Qt und LibRaw beizulegen.
