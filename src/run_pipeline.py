"""Führt die komplette Datenpipeline mit einem Befehl aus.

Was ist die Pipeline?
---------------------- 
klassischer ETL-Prozess (Extract, Transform, Load), wie er auch in Data-Warehouse-Umgebungen läuft:

    1. clean.py       Rohdaten bereinigen                 -> fundamentals_clean.csv
    2. transform.py   Kennzahlen berechnen                -> fundamentals_enriched.csv
    3. plan.py        Planwerte erzeugen                  -> plan.csv
    4. load_to_db.py  Ist + Plan in die Datenbank laden   -> finance.db

Was dieses Skript zusätzlich leistet
------------------------------------
- Feste Reihenfolge: Niemand muss sich merken, welches Skript wann laufen muss.
- Abbruch bei Fehlern: Schlägt ein Schritt fehl, laufen die folgenden NICHT weiter.
  So landen nie halbfertige oder veraltete Daten in der Datenbank.
- Protokoll (Log): Jeder Lauf wird mit Zeitstempel und Dauer je Schritt in
  logs/pipeline.log festgehalten. Damit ist später nachvollziehbar, wann die Daten
  zuletzt aktualisiert wurden und ob dabei Fehler auftraten.

Aufruf (im Projektordner): uv run python src/run_pipeline.py
"""

import logging
import sys
import time
from pathlib import Path

# Die vier Pipeline-Schritte liegen als eigene Skripte im selben Ordner (src/).
# Beim Start mit "python src/run_pipeline.py" steht src/ automatisch im Suchpfad,
# daher lassen sie sich direkt importieren. Jedes Skript hat eine Funktion main(),
# die genau das tut, was auch beim einzelnen Aufruf des Skripts passiert.
import clean
import load_to_db
import plan
import transform

ROOT = Path(__file__).resolve().parents[1]
RAW_INPUTS = [
    ROOT / "data" / "raw" / "fundamentals.csv",
    ROOT / "data" / "raw" / "securities.csv",
]
LOG_FILE = ROOT / "logs" / "pipeline.log"

# Die Schritte in Ausführungsreihenfolge: (Anzeigename, aufzurufende Funktion).
# Ein neuer Schritt wird einfach an der passenden Stelle in diese Liste eingefügt.
STEPS = [
    ("1/4 Bereinigung (clean.py)", clean.main),
    ("2/4 Kennzahlen (transform.py)", transform.main),
    ("3/4 Planung (plan.py)", plan.main),
    ("4/4 Laden in Datenbank (load_to_db.py)", load_to_db.main),
]

log = logging.getLogger("pipeline")


def setup_logging() -> None:
    """Schreibt Meldungen gleichzeitig in die Konsole und in logs/pipeline.log."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # mode="a" (append): neue Läufe werden angehängt, ältere Einträge bleiben als Historie erhalten
    file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    console_handler = logging.StreamHandler(sys.stdout)
    for handler in (file_handler, console_handler):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.setLevel(logging.INFO)


def check_inputs() -> None:
    """Prüft vor dem Start, ob alle Rohdateien vorhanden sind.

    Lieber sofort mit einer klaren Meldung abbrechen als erst mitten in Schritt 4
    mit einer unverständlichen Fehlermeldung.
    """
    missing = [p for p in RAW_INPUTS if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Rohdaten fehlen: " + ", ".join(str(p.relative_to(ROOT)) for p in missing)
        )


def run() -> int:
    """Führt alle Schritte nacheinander aus. Rückgabe: 0 = Erfolg, 1 = Fehler."""
    setup_logging()
    log.info("=" * 60)
    log.info("Pipeline gestartet")
    pipeline_start = time.perf_counter()

    try:
        check_inputs()

        for name, step in STEPS:
            log.info(f"START  {name}")
            step_start = time.perf_counter()

            # Hier läuft der eigentliche Schritt. Seine Kontrollausgaben (print)
            # erscheinen in der Konsole, landen aber nicht im Log.
            step()

            duration = time.perf_counter() - step_start
            log.info(f"OK     {name} ({duration:.1f} s)")

    except Exception:
        # log.exception schreibt die Fehlermeldung inkl. Stelle im Code (Traceback) ins Log.
        # Durch das return werden alle folgenden Schritte übersprungen.
        log.exception("Pipeline ABGEBROCHEN - nachfolgende Schritte wurden nicht ausgeführt")
        return 1

    total = time.perf_counter() - pipeline_start
    log.info(f"Pipeline erfolgreich beendet ({total:.1f} s)")
    return 0


if __name__ == "__main__":
    # Der Rückgabewert wird als Exit-Code an das Betriebssystem gemeldet (0 = Erfolg).
    # Das ist wichtig, wenn die Pipeline später automatisch gestartet wird, z.B. per
    # Windows-Aufgabenplanung: Dort lässt sich so erkennen, ob der Lauf geklappt hat.
    sys.exit(run())
