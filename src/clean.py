"""Bereinigt data/raw/fundamentals.csv und schreibt data/processed/fundamentals_clean.csv.

Aufruf: uv run python src/clean.py
"""

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "fundamentals.csv"
OUT = ROOT / "data" / "processed" / "fundamentals_clean.csv"

# Geschäftsjahre, die bis einschließlich Mai enden, zählen zum Vorjahr
# (z.B. Einzelhändler mit Jahresende Ende Januar/Anfang Februar).
FISCAL_YEAR_CUTOFF_MONTH = 5
# Alles davor ist im Datensatz nur vereinzelt vorhanden und unplausibel (COTY 2003–2007).
MIN_FISCAL_YEAR = 2010


def to_snake_case(name: str) -> str:
    name = name.replace("&", "and").replace("/", " ")
    name = re.sub(r"[^0-9a-zA-Z]+", "_", name)
    return name.strip("_").lower()


def clean(df: pd.DataFrame) -> pd.DataFrame:
    # Index-Spalte aus dem CSV-Export entfernen
    df = df.drop(columns=[c for c in df.columns if c.startswith("Unnamed")])
    df.columns = [to_snake_case(c) for c in df.columns]

    # Datentypen
    df["ticker_symbol"] = df["ticker_symbol"].str.strip().str.upper()
    df["period_ending"] = pd.to_datetime(df["period_ending"], format="%Y-%m-%d")
    numeric_cols = df.columns.difference(["ticker_symbol", "period_ending"])
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")

    # "For Year" ist lückenhaft (173 fehlend), teils falsch (1215) und erzeugt doppelte
    # Ticker/Jahr-Paare -> Geschäftsjahr stattdessen aus dem Periodenende ableiten.
    df = df.drop(columns="for_year")
    df.insert(
        2,
        "fiscal_year",
        df["period_ending"].dt.year
        - (df["period_ending"].dt.month <= FISCAL_YEAR_CUTOFF_MONTH).astype(int),
    )

    # Pflichtfelder: ohne Ticker, Datum oder Umsatz ist eine Zeile nicht verwertbar
    df = df.dropna(subset=["ticker_symbol", "period_ending", "total_revenue"])
    df = df[df["fiscal_year"] >= MIN_FISCAL_YEAR]

    # Duplikate: exakte Kopien und mehrere Berichte pro Unternehmen/Jahr (jüngsten behalten)
    df = df.drop_duplicates()
    df = df.sort_values(["ticker_symbol", "period_ending"])
    df = df.drop_duplicates(subset=["ticker_symbol", "fiscal_year"], keep="last")

    # Übrige fehlende Werte (z.B. Current Ratio bei Banken, EPS) bleiben bewusst NaN:
    # Finanzkennzahlen zu schätzen würde die Analyse verfälschen.
    return df.reset_index(drop=True)


def main() -> None:
    raw = pd.read_csv(RAW)
    df = clean(raw)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)

    print(f"Rohdaten:   {raw.shape[0]} Zeilen, {raw.shape[1]} Spalten")
    print(f"Bereinigt:  {df.shape[0]} Zeilen, {df.shape[1]} Spalten -> {OUT.relative_to(ROOT)}")
    print(f"Unternehmen: {df['ticker_symbol'].nunique()}, Jahre: {df['fiscal_year'].min()}–{df['fiscal_year'].max()}")
    missing = df.isna().sum()
    print("Verbleibende fehlende Werte:")
    print(missing[missing > 0].to_string())


if __name__ == "__main__":
    main()
