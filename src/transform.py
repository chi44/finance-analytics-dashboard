"""Berechnet zusätzliche Kennzahlen und schreibt data/processed/fundamentals_enriched.csv.

Voraussetzung: src/clean.py wurde ausgeführt.
Aufruf: uv run python src/transform.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "data" / "processed" / "fundamentals_clean.csv"
OUT = ROOT / "data" / "processed" / "fundamentals_enriched.csv"


def safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan)


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values(["ticker_symbol", "fiscal_year"]).copy()

    # Banken/Versicherer weisen keine Herstellkosten aus (Cost of Revenue = 0).
    # Kostenquote/Bruttomarge wären dort 0 % bzw. 100 % -> als "nicht anwendbar" (NaN) führen.
    has_cogs = df["cost_of_revenue"] > 0
    df["has_cost_of_revenue"] = has_cogs

    df["cost_ratio"] = safe_divide(df["cost_of_revenue"], df["total_revenue"]).where(has_cogs)
    df["gross_margin_ratio"] = safe_divide(df["gross_profit"], df["total_revenue"]).where(has_cogs)
    df["net_margin_ratio"] = safe_divide(df["net_income"], df["total_revenue"])

    # YoY nur gegen das direkt vorangehende Geschäftsjahr, nicht über Datenlücken hinweg
    prev = df.groupby("ticker_symbol")[["fiscal_year", "total_revenue"]].shift(1)
    consecutive = prev["fiscal_year"] == df["fiscal_year"] - 1
    df["revenue_prev_year"] = prev["total_revenue"].where(consecutive)
    df["revenue_yoy_change"] = df["total_revenue"] - df["revenue_prev_year"]
    df["revenue_yoy_pct"] = safe_divide(df["revenue_yoy_change"], df["revenue_prev_year"].abs())

    return df.reset_index(drop=True)


def main() -> None:
    df = enrich(pd.read_csv(CLEAN, parse_dates=["period_ending"]))
    df.to_csv(OUT, index=False)

    print(f"Angereichert: {df.shape[0]} Zeilen, {df.shape[1]} Spalten -> {OUT.relative_to(ROOT)}")
    cols = ["ticker_symbol", "fiscal_year", "total_revenue", "cost_ratio",
            "gross_margin_ratio", "net_margin_ratio", "revenue_yoy_pct"]
    print("\nBeispiel (Apple):")
    print(df.loc[df["ticker_symbol"] == "AAPL", cols].to_string(index=False))
    print("\nKennzahlen-Übersicht:")
    print(df[cols[3:]].describe().round(3).to_string())


if __name__ == "__main__":
    main()
