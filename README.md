# Finance Analytics Dashboard

Portfolio-Projekt: Aufbereitung von Finanzkennzahlen der S&P-500-Unternehmen mit Python,
Modellierung in einem SQL-Star-Schema und Visualisierung in Power BI, inklusive
Plan-Ist-Vergleich.

## Datenquelle

Kaggle-Datensatz **„New York Stock Exchange“** (S&P-500-Fundamentaldaten 2012–2016):
https://www.kaggle.com/datasets/dgawlik/nyse

Benötigt werden diese Dateien in `data/raw/`:

| Datei | Inhalt | Im Repo |
|---|---|---|
| `fundamentals.csv` | Jahresabschlusskennzahlen je Unternehmen und Jahr | ja |
| `securities.csv` | Stammdaten: Name, GICS-Sektor, Branche | ja |
| `prices.csv`, `prices-split-adjusted.csv` | tägliche Aktienkurse | nein (je ~50 MB, im Projekt nicht genutzt) |

## Setup und Ausführung

Voraussetzung: [uv](https://docs.astral.sh/uv/) ist installiert.

```bash
uv sync                              # Abhängigkeiten installieren
uv run python src/run_pipeline.py    # komplette Pipeline ausführen
```

Die Pipeline erzeugt alle Dateien in `data/processed/` sowie die SQLite-Datenbank
`data/processed/finance.db`. Diese Dateien sind nicht versioniert, da sie jederzeit
neu erzeugt werden können.

## Pipeline

```
data/raw/fundamentals.csv
   │
   ├─ 1. src/clean.py       Bereinigung       -> fundamentals_clean.csv
   ├─ 2. src/transform.py   Kennzahlen        -> fundamentals_enriched.csv
   ├─ 3. src/plan.py        Planwerte         -> plan.csv
   └─ 4. src/load_to_db.py  Laden (SQLite)    -> finance.db  (Schema: sql/schema.sql)
```

> Die Planwerte sind **simuliert** (Trendfortschreibung) und keine echten Unternehmensplanungen.
