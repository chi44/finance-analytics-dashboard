-- Star-Schema für S&P-500-Fundamentaldaten (SQLite)
--
--                 1 ──< n fact_financials   (Ist-Werte)
--   dim_company
--                 1 ──< n fact_plan         (simulierte Planwerte, src/plan.py)
--
-- Beide Faktentabellen haben dieselbe Granularität: ein Unternehmen je Geschäftsjahr.
-- Plan und Ist liegen bewusst in getrennten Tabellen (wie in einem Data Warehouse üblich):
-- Sie stammen aus unterschiedlichen Quellen, werden zu unterschiedlichen Zeitpunkten
-- erstellt und sind nicht für jedes Ist-Jahr vorhanden.
-- Quotenspalten (*_ratio, *_pct) sind Dezimalwerte, z.B. 0.38 = 38 %.

-- Reihenfolge beim Löschen: erst View und Faktentabellen, dann die Dimension,
-- weil die Faktentabellen per Fremdschlüssel auf dim_company verweisen.
DROP VIEW  IF EXISTS v_plan_vs_actual;
DROP TABLE IF EXISTS fact_plan;
DROP TABLE IF EXISTS fact_financials;
DROP TABLE IF EXISTS dim_company;

CREATE TABLE dim_company (
    company_id          INTEGER PRIMARY KEY,
    ticker_symbol       TEXT    NOT NULL UNIQUE,
    company_name        TEXT    NOT NULL,
    gics_sector         TEXT    NOT NULL,
    gics_sub_industry   TEXT,
    headquarters        TEXT,
    date_first_added    DATE,
    cik                 INTEGER
);

CREATE TABLE fact_financials (
    financials_id                 INTEGER PRIMARY KEY,
    company_id                    INTEGER NOT NULL REFERENCES dim_company (company_id),
    fiscal_year                   INTEGER NOT NULL,
    period_ending                 DATE    NOT NULL,

    -- Gewinn- und Verlustrechnung (USD)
    total_revenue                 REAL    NOT NULL,
    cost_of_revenue               REAL,
    gross_profit                  REAL,
    sales_general_and_admin       REAL,
    research_and_development      REAL,
    operating_income              REAL,
    earnings_before_interest_and_tax REAL,
    net_income                    REAL,
    earnings_per_share            REAL,

    -- Bilanz (USD)
    total_assets                  REAL,
    total_liabilities             REAL,
    total_equity                  REAL,
    cash_and_cash_equivalents     REAL,
    long_term_debt                REAL,

    -- Cashflow (USD)
    net_cash_flow_operating       REAL,
    capital_expenditures          REAL,

    -- Berechnete Kennzahlen (src/transform.py)
    has_cost_of_revenue           INTEGER NOT NULL,  -- 0 = z.B. Bank/Versicherer, Bruttokennzahlen n/a
    cost_ratio                    REAL,
    gross_margin_ratio            REAL,
    net_margin_ratio              REAL,
    revenue_prev_year             REAL,
    revenue_yoy_change            REAL,
    revenue_yoy_pct               REAL,

    UNIQUE (company_id, fiscal_year)
);

CREATE INDEX ix_fact_financials_fiscal_year ON fact_financials (fiscal_year);

CREATE TABLE fact_plan (
    plan_id                       INTEGER PRIMARY KEY,
    company_id                    INTEGER NOT NULL REFERENCES dim_company (company_id),
    fiscal_year                   INTEGER NOT NULL,

    -- Planannahme und Planwerte (USD)
    plan_revenue_growth           REAL    NOT NULL,  -- angenommenes Umsatzwachstum, z.B. 0.05 = +5 %
    plan_revenue                  REAL    NOT NULL,
    plan_cost_of_revenue          REAL,              -- NULL bei Unternehmen ohne Herstellkosten
    plan_gross_profit             REAL,
    plan_net_income               REAL,

    -- Dokumentation der Planungsmethode für Nachvollziehbarkeit (Data Governance)
    planning_method               TEXT    NOT NULL,

    UNIQUE (company_id, fiscal_year)
);

-- Plan-Ist-Vergleich als fertige View: Power BI oder SQL-Abfragen können die
-- Abweichungen direkt nutzen, die Berechnungslogik liegt zentral an einer Stelle.
--
-- Vorzeichenkonvention: Abweichung = Ist - Plan
--   positiv bei Umsatz/Gewinn  = besser als geplant
--   positiv bei Kosten         = schlechter als geplant (mehr Kosten als geplant)
CREATE VIEW v_plan_vs_actual AS
SELECT
    p.company_id,
    c.ticker_symbol,
    c.company_name,
    c.gics_sector,
    c.gics_sub_industry,
    p.fiscal_year,

    -- Umsatz
    p.plan_revenue,
    f.total_revenue                                      AS actual_revenue,
    f.total_revenue - p.plan_revenue                     AS revenue_variance,
    (f.total_revenue - p.plan_revenue) / p.plan_revenue  AS revenue_variance_pct,

    -- Herstellkosten
    p.plan_cost_of_revenue,
    CASE WHEN f.has_cost_of_revenue = 1 THEN f.cost_of_revenue END AS actual_cost_of_revenue,
    CASE WHEN f.has_cost_of_revenue = 1
         THEN f.cost_of_revenue - p.plan_cost_of_revenue END       AS cost_of_revenue_variance,

    -- Bruttogewinn
    p.plan_gross_profit,
    CASE WHEN f.has_cost_of_revenue = 1 THEN f.gross_profit END    AS actual_gross_profit,
    CASE WHEN f.has_cost_of_revenue = 1
         THEN f.gross_profit - p.plan_gross_profit END             AS gross_profit_variance,

    -- Jahresüberschuss
    p.plan_net_income,
    f.net_income                                         AS actual_net_income,
    f.net_income - p.plan_net_income                     AS net_income_variance
FROM fact_plan p
-- INNER JOIN: nur Jahre, für die sowohl Plan als auch Ist vorliegen
JOIN fact_financials f ON f.company_id = p.company_id AND f.fiscal_year = p.fiscal_year
JOIN dim_company     c ON c.company_id = p.company_id;
