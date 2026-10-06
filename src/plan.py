"""Erzeugt Planwerte je Unternehmen und Geschäftsjahr für den Plan-Ist-Vergleich.

Hintergrund
-----------
Die Rohdaten enthalten nur Ist-Werte aus veröffentlichten Jahresabschlüssen. Um einen
Plan-Ist-Vergleich (Abweichungsanalyse) zeigen zu können, simuliert dieses Skript eine
einfache, in der Praxis übliche Top-down-Planung:

1. Umsatzplanung über den Trend:
       Planumsatz(J) = Istumsatz(J-1) × (1 + Ø Umsatzwachstum der letzten bis zu 3 Jahre)
2. Kostenplanung über Quoten:
       Plan-Herstellkosten(J) = Planumsatz(J) × Kostenquote(J-1)
       Plan-Jahresüberschuss(J) = Planumsatz(J) × Nettomarge(J-1)
3. Plan-Bruttogewinn(J) = Planumsatz(J) - Plan-Herstellkosten(J)

Wichtig: Der Plan für Jahr J verwendet ausschließlich Daten bis einschließlich J-1, also
nur das, was ein Controller bei der Budgetierung Ende J-1 tatsächlich gewusst hätte.
Ein Plan, der schon das Ist-Ergebnis kennt, wäre wertlos.

Hinweis: Die Planwerte sind simuliert und keine echten Unternehmensplanungen.

Voraussetzung: src/clean.py und src/transform.py wurden ausgeführt.
Aufruf: uv run python src/plan.py
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ENRICHED = ROOT / "data" / "processed" / "fundamentals_enriched.csv"
OUT = ROOT / "data" / "processed" / "plan.csv"

# Wie viele vergangene Wachstumsraten fließen in die Trendannahme ein?
GROWTH_LOOKBACK_YEARS = 3

# Kappung der Wachstumsannahme: Einmaleffekte wie Übernahmen (+100 % Umsatz) würde
# kein Controller unverändert fortschreiben. Werte außerhalb dieser Spanne werden begrenzt.
MIN_GROWTH = -0.20
MAX_GROWTH = 0.30

PLANNING_METHOD = (
    f"Trend: Vorjahr x (1 + Ø-Wachstum letzte {GROWTH_LOOKBACK_YEARS} J., "
    f"gekappt {MIN_GROWTH:+.0%}..{MAX_GROWTH:+.0%}); Kosten/Gewinn über Vorjahresquoten"
)


def build_plan(df: pd.DataFrame) -> pd.DataFrame:
    # Sortierung ist Voraussetzung für shift()/rolling(): Jahre müssen je Unternehmen
    # chronologisch aufsteigend vorliegen
    df = df.sort_values(["ticker_symbol", "fiscal_year"]).reset_index(drop=True)
    by_company = df.groupby("ticker_symbol")

    # --- Basisjahr (J-1) -------------------------------------------------------
    # shift(1) holt je Unternehmen die Werte der vorherigen Zeile, also des Vorjahres.
    base = by_company[["fiscal_year", "total_revenue", "cost_ratio", "net_margin_ratio"]].shift(1)

    # Nur planen, wenn das Vorjahr lückenlos vorhanden ist (kein Sprung von 2013 auf 2015)
    has_base_year = base["fiscal_year"] == df["fiscal_year"] - 1

    # --- Wachstumsannahme --------------------------------------------------------
    # revenue_yoy_pct in Zeile J ist das Wachstum von J-1 auf J. Für den Plan von J ist
    # das noch unbekannt, daher erst um ein Jahr verschieben (shift) und dann den
    # Durchschnitt über die letzten bis zu 3 bekannten Wachstumsraten bilden.
    growth_assumption = by_company["revenue_yoy_pct"].transform(
        lambda s: s.shift(1).rolling(GROWTH_LOOKBACK_YEARS, min_periods=1).mean()
    )
    growth_assumption = growth_assumption.clip(MIN_GROWTH, MAX_GROWTH)

    # --- Planwerte berechnen -------------------------------------------------------
    plan = pd.DataFrame({
        "ticker_symbol": df["ticker_symbol"],
        "fiscal_year": df["fiscal_year"],
        "plan_revenue_growth": growth_assumption,
        "plan_revenue": base["total_revenue"] * (1 + growth_assumption),
    })
    # Kostenquote ist bei Banken/Versicherern NaN (keine Herstellkosten) ->
    # Plan-Herstellkosten und Plan-Bruttogewinn bleiben dort automatisch leer
    plan["plan_cost_of_revenue"] = plan["plan_revenue"] * base["cost_ratio"]
    plan["plan_gross_profit"] = plan["plan_revenue"] - plan["plan_cost_of_revenue"]
    plan["plan_net_income"] = plan["plan_revenue"] * base["net_margin_ratio"]
    plan["planning_method"] = PLANNING_METHOD

    # Nur Zeilen behalten, für die ein vollständiger Umsatzplan möglich war.
    # Das erste vorhandene Jahr je Unternehmen fällt immer weg (kein Vorjahr) und das
    # zweite ebenfalls (noch keine Wachstumsrate bekannt) -> Plan ab dem 3. Jahr.
    valid = has_base_year & plan["plan_revenue"].notna()
    return plan[valid].reset_index(drop=True)


def main() -> None:
    actual = pd.read_csv(ENRICHED)
    plan = build_plan(actual)
    plan.to_csv(OUT, index=False)

    print(f"Plan erzeugt: {len(plan)} Zeilen, {plan['ticker_symbol'].nunique()} Unternehmen "
          f"-> {OUT.relative_to(ROOT)}")
    print("Planzeilen je Geschäftsjahr:")
    print(plan["fiscal_year"].value_counts().sort_index().to_string())

    # Kurzer Plan-Ist-Abgleich als Plausibilitätskontrolle: Wie gut trifft der Plan?
    check = plan.merge(actual[["ticker_symbol", "fiscal_year", "total_revenue"]],
                       on=["ticker_symbol", "fiscal_year"])
    check["abweichung_pct"] = check["total_revenue"] / check["plan_revenue"] - 1
    print("\nUmsatzabweichung Ist vs. Plan (Median / Anteil innerhalb ±5 %):")
    print(f"  Median: {check['abweichung_pct'].median():+.1%}")
    print(f"  Innerhalb ±5 %: {(check['abweichung_pct'].abs() <= 0.05).mean():.0%}")

    print("\nBeispiel Walmart (WMT):")
    wmt = check[check["ticker_symbol"] == "WMT"]
    print((wmt[["fiscal_year", "plan_revenue_growth", "plan_revenue", "total_revenue", "abweichung_pct"]]
           .assign(plan_revenue=lambda d: (d["plan_revenue"] / 1e9).round(1),
                   total_revenue=lambda d: (d["total_revenue"] / 1e9).round(1))
           .rename(columns={"plan_revenue": "plan_mrd", "total_revenue": "ist_mrd"})
           .to_string(index=False)))


if __name__ == "__main__":
    main()
