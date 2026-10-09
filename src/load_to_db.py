"""Lädt Ist- und Plandaten gemäß sql/schema.sql in die SQLite-Datenbank data/processed/finance.db.

Ablauf
------
1. Schema aus sql/schema.sql ausführen (löscht alte Tabellen und legt sie neu an)
2. Dimension dim_company aus securities.csv aufbauen (Name, Sektor, Branche)
3. Faktentabellen fact_financials (Ist) und fact_plan (Plan) befüllen
4. Kontrollausgaben: Zeilenanzahlen und Beispielabfragen

Das Skript ist idempotent: Es kann beliebig oft ausgeführt werden und liefert immer
denselben Datenbankstand, ohne Daten doppelt zu laden.

Voraussetzung: src/clean.py, src/transform.py und src/plan.py wurden ausgeführt.
Aufruf: uv run python src/load_to_db.py
"""

from pathlib import Path

import pandas as pd
from sqlalchemy import Connection, create_engine, event, text

ROOT = Path(__file__).resolve().parents[1]
ENRICHED = ROOT / "data" / "processed" / "fundamentals_enriched.csv"
PLAN = ROOT / "data" / "processed" / "plan.csv"
SECURITIES = ROOT / "data" / "raw" / "securities.csv"
SCHEMA = ROOT / "sql" / "schema.sql"
DB = ROOT / "data" / "processed" / "finance.db"
# Exporte für Power BI: So kann Power BI reine CSV-Dateien laden und braucht
# keinen zusätzlichen ODBC-Treiber für SQLite
POWERBI_DIR = ROOT / "data" / "processed" / "powerbi"


def build_dim_company(securities: pd.DataFrame, tickers: pd.Series) -> pd.DataFrame:
    """Baut die Unternehmensdimension: eine Zeile je Unternehmen mit Stammdaten."""
    # Spaltennamen der Quelldatei auf die Namen im Schema abbilden
    dim = securities.rename(columns={
        "Ticker symbol": "ticker_symbol",
        "Security": "company_name",
        "GICS Sector": "gics_sector",
        "GICS Sub Industry": "gics_sub_industry",
        "Address of Headquarters": "headquarters",
        "Date first added": "date_first_added",
        "CIK": "cik",
    })
    # Gleiche Schreibweise wie in clean.py, damit der Abgleich der Ticker sicher funktioniert
    dim["ticker_symbol"] = dim["ticker_symbol"].str.strip().str.upper()

    # Nur Unternehmen übernehmen, für die es auch Finanzdaten gibt
    # (securities.csv enthält 505 Einträge, Fundamentaldaten gibt es für 447)
    dim = dim[dim["ticker_symbol"].isin(tickers)].sort_values("ticker_symbol")
    dim = dim[["ticker_symbol", "company_name", "gics_sector", "gics_sub_industry",
               "headquarters", "date_first_added", "cik"]].reset_index(drop=True)

    # Surrogatschlüssel: eine fortlaufende Nummer als technischer Primärschlüssel.
    # Vorteil gegenüber dem Ticker: Ticker können sich ändern (z.B. nach Umfirmierung),
    # die ID bleibt stabil, und Ganzzahl-Joins sind in BI-Tools schneller.
    dim.insert(0, "company_id", dim.index + 1)
    return dim


def add_company_id(df: pd.DataFrame, dim: pd.DataFrame) -> pd.DataFrame:
    """Ersetzt den Ticker durch den Fremdschlüssel company_id aus der Dimension."""
    # validate="many_to_one": bricht ab, falls ein Ticker in der Dimension doppelt wäre
    return df.merge(dim[["company_id", "ticker_symbol"]], on="ticker_symbol",
                    how="inner", validate="many_to_one")


def table_columns(conn: Connection, table: str) -> list[str]:
    """Liest die Spaltennamen einer Tabelle aus der Datenbank.

    So bestimmt allein schema.sql, welche Spalten geladen werden: Spalten aus der CSV,
    die im Schema nicht vorkommen, werden ignoriert.
    """
    return [row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")]


def build_fact_financials(enriched: pd.DataFrame, dim: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Bereitet die Ist-Faktentabelle auf."""
    fact = add_company_id(enriched, dim)
    # SQLite kennt keinen echten Datumstyp -> Datum als ISO-Text speichern (YYYY-MM-DD)
    fact["period_ending"] = pd.to_datetime(fact["period_ending"]).dt.strftime("%Y-%m-%d")
    # Wahrheitswerte als 0/1 speichern (SQLite hat keinen BOOLEAN-Typ)
    fact["has_cost_of_revenue"] = fact["has_cost_of_revenue"].astype(int)
    fact = fact.sort_values(["company_id", "fiscal_year"]).reset_index(drop=True)
    fact["financials_id"] = fact.index + 1
    return fact[columns]


def build_fact_plan(plan: pd.DataFrame, dim: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Bereitet die Plan-Faktentabelle auf."""
    fact = add_company_id(plan, dim)
    fact = fact.sort_values(["company_id", "fiscal_year"]).reset_index(drop=True)
    fact["plan_id"] = fact.index + 1
    return fact[columns]


def main() -> None:
    engine = create_engine(f"sqlite:///{DB}")

    # SQLite prüft Fremdschlüssel standardmäßig NICHT. Dieser Hook schaltet die Prüfung
    # für jede neue Verbindung ein, damit z.B. keine Planzeile ohne Unternehmen entsteht.
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys = ON")

    enriched = pd.read_csv(ENRICHED)
    plan = pd.read_csv(PLAN)
    dim = build_dim_company(pd.read_csv(SECURITIES), enriched["ticker_symbol"])

    # engine.begin() öffnet eine Transaktion: Entweder wird alles geladen oder bei einem
    # Fehler gar nichts. So bleibt die Datenbank nie in einem halb geladenen Zustand.
    with engine.begin() as conn:
        # schema.sql enthält mehrere Anweisungen -> executescript des SQLite-Treibers nutzen
        conn.connection.driver_connection.executescript(SCHEMA.read_text(encoding="utf-8"))

        fact = build_fact_financials(enriched, dim, table_columns(conn, "fact_financials"))
        fact_plan = build_fact_plan(plan, dim, table_columns(conn, "fact_plan"))

        # if_exists="append": in die von schema.sql angelegten Tabellen schreiben.
        # ("replace" würde die Tabellen neu erzeugen und dabei Schlüssel und Regeln verlieren.)
        # Reihenfolge wichtig: zuerst die Dimension, auf die die Fakten verweisen.
        dim.to_sql("dim_company", conn, if_exists="append", index=False)
        fact.to_sql("fact_financials", conn, if_exists="append", index=False)
        fact_plan.to_sql("fact_plan", conn, if_exists="append", index=False)

    # --- Export für Power BI --------------------------------------------------------
    # Die Daten werden aus der Datenbank gelesen (nicht aus den DataFrames), damit Power BI
    # exakt den geprüften Datenbankstand inkl. der Plan-Ist-Logik aus der View erhält.
    POWERBI_DIR.mkdir(parents=True, exist_ok=True)
    with engine.connect() as conn:
        exports = {
            "dim_company.csv": "SELECT * FROM dim_company",
            "plan_vs_actual.csv": "SELECT * FROM v_plan_vs_actual",
        }
        for filename, query in exports.items():
            pd.read_sql(text(query), conn).to_csv(POWERBI_DIR / filename, index=False)

    # --- Kontrollausgaben ---------------------------------------------------------------
    with engine.connect() as conn:
        counts = {t: conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar_one()
                  for t in ["dim_company", "fact_financials", "fact_plan", "v_plan_vs_actual"]}
        print(f"{DB.relative_to(ROOT)}:")
        for table, n in counts.items():
            print(f"  {table:<18} {n:>5} Zeilen")

        print("\nBeispielabfrage 1 - Durchschnittliche Bruttomarge und Umsatzwachstum je Sektor (GJ 2015):")
        print(pd.read_sql(text("""
            SELECT c.gics_sector,
                   COUNT(*)                                  AS companies,
                   ROUND(SUM(f.total_revenue) / 1e9, 1)      AS revenue_bn_usd,
                   ROUND(AVG(f.gross_margin_ratio) * 100, 1) AS avg_gross_margin_pct,
                   ROUND(AVG(f.revenue_yoy_pct) * 100, 1)    AS avg_revenue_yoy_pct
            FROM fact_financials f
            JOIN dim_company c USING (company_id)
            WHERE f.fiscal_year = 2015
            GROUP BY c.gics_sector
            ORDER BY revenue_bn_usd DESC
        """), conn).to_string(index=False))

        # Plan-Ist-Vergleich je Händler über die View v_plan_vs_actual: Die Abweichungslogik
        # steht zentral in schema.sql, die Abfrage muss nur noch filtern und formatieren.
        print("\nBeispielabfrage 2 - Plan-Ist-Vergleich Umsatz im Einzelhandel (GJ 2015, Mrd. USD):")
        print(pd.read_sql(text("""
            SELECT ticker_symbol,
                   company_name,
                   ROUND(plan_revenue / 1e9, 1)          AS plan_bn,
                   ROUND(actual_revenue / 1e9, 1)        AS actual_bn,
                   ROUND(revenue_variance / 1e9, 2)      AS variance_bn,
                   ROUND(revenue_variance_pct * 100, 1)  AS variance_pct
            FROM v_plan_vs_actual
            WHERE fiscal_year = 2015
              AND gics_sub_industry IN ('Drug Retail', 'Food Retail',
                                        'Hypermarkets & Super Centers', 'General Merchandise Stores')
            ORDER BY actual_revenue DESC
        """), conn).to_string(index=False))


if __name__ == "__main__":
    main()
