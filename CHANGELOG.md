# Changelog

## 0.3.0 – 2026-11-21

- Neues **Rechenprotokoll**: Während der Analyse fährt rechts ein Panel herein, das live zeigt, wie die
  Berechnung abläuft – Datei öffnen, Objekterkennung, Messwerte jedes Frames, Frame-Qualität,
  Stacking-Empfehlung und die Score-Formel mit eingesetzten Werten. Mit Syntax-Hervorhebung,
  automatischem Mitlaufen, Kopieren und Leeren; ein-/ausblendbar über *Analyse › Rechenprotokoll* (Strg+L)
  oder automatisch bei jeder Analyse (Einstellungen › Allgemein).

## 0.2.0 – 2026-11-21

Neues Erscheinungsbild und Deep-Sky-Unterstützung.

- Neues Logo (Blende mit Orbit) und Startbildschirm mit Slogan „Analyse. Entscheide. Perfektioniere.“
- Willkommensdialog mit Schnellstart: Ordner analysieren, Video analysieren, Projekt öffnen, Objektwahl,
  „Nicht mehr anzeigen“
- Neue Oberfläche: Menüleiste, Seitenleiste (Übersicht, Analyse, Berichte, Einstellungen, Info)
- Übersicht-Dashboard: Empfehlungsquote, Ø-Qualitäts-Score mit Trend, Top-Ergebnisse, Gesamtzeit,
  Details/Ausschluss-Gründe/Empfehlungen, Vorschau mit Zoom bis 400 % (Originalauflösung)
- Kurzbegründung je Datei (z. B. „Kleine FWHM, runde Sterne“)
- Deep-Sky-Profil: FWHM, Exzentrizität/Nachführung, Sternanzahl/Transparenz, Himmelshintergrund,
  Bildfeld-Gleichmäßigkeit, Fokusdrift-Erkennung über die Session
- Projekte (.ffproj) speichern und öffnen – ohne erneute Analyse
- Videos: zusätzlich MP4, MOV, MKV, M4V
- Urteil „Nicht empfohlen“ heißt jetzt „Abgelehnt“
- Einstellungen als eigene Seite, Änderungen werden sofort gespeichert
- Protokolldatei, Fehlerdialog mit „Problem melden“, Hilfe-Menü (Anleitung, Protokollordner)
- Deutsche Texte in Qt-Standarddialogen
- Dateizuordnung: Doppelklick auf .ffproj, „Öffnen mit“ für SER/FITS; macOS-Finder-Öffnen
- Pfade mit Umlauten unter Windows (Videos, RAW)
- Robustere Release-Pipeline (nur Binärpakete, Zeitlimit, Teil-Releases), Issue-Vorlagen, Dependabot


## 0.1.0 – 2026-11-21

Erste Version.

- Qualitätsanalyse für SER, AVI, FITS, TIFF, RAW, PNG/JPEG
- Metriken: Schärfe (rauschkorrigiert), Kontrast, Rauschen/SNR, Belichtung/Clipping, Bildstabilität, Bewegungsunschärfe, lokale Qualität
- Profile für Planeten, Mond, Sonne und Allgemein
- Session-Ranking mit Begründungen und Empfehlungen
- Frame-Selektion und Export der besten Frames als SER
- Qualitätsverlauf und Session-Vergleich
- Desktop-Oberfläche mit Splash-Screen, Einstellungen und In-App-Updates über GitHub Releases
- Kommandozeile `frameforge analyze`
- Build-Pipeline für Windows (Inno Setup) und macOS (DMG)
