-- Meridian structured tables for Extra-Credit Assignment 1, Part 2.
-- The executable, parameterized version is genie/build_tables.py.
--
-- Source derivation:
-- * FY2023 segment rows are transcribed from data/annual_report.md.
-- * FY2022/FY2023 income-statement rows are transcribed from the report.
-- * The report does not disclose FY2022 by-segment figures. Those four rows are
--   plausible synthesized allocations and reconcile exactly to reported FY2022
--   net revenue (JPY 14.55T) and operating profit (JPY 905B).

CREATE OR REPLACE TABLE cs4603.pa4.meridian_segment_financials (
  fiscal_year INT NOT NULL COMMENT 'Fiscal year ending March 31, expressed as a four-digit year.',
  segment STRING NOT NULL COMMENT 'Meridian reportable business segment.',
  revenue_yen BIGINT NOT NULL COMMENT 'External net revenue in raw Japanese yen.',
  operating_income_yen BIGINT NOT NULL COMMENT 'Segment operating profit in raw Japanese yen.',
  units_sold BIGINT COMMENT 'Units sold in the fiscal year; NULL for non-unit-based segments.'
)
USING DELTA
COMMENT 'Meridian reportable-segment financials for FY2022-FY2023.';

INSERT OVERWRITE cs4603.pa4.meridian_segment_financials VALUES
  (2022, 'Automobile',             11030000000000, 430000000000,  3680000),
  (2022, 'Motorcycle',              2120000000000, 310000000000, 17000000),
  (2022, 'Financial Services',       1030000000000, 145000000000,     NULL),
  (2022, 'Power Products & Other',    370000000000,  20000000000,     NULL),
  (2023, 'Automobile',             12900000000000, 560000000000,  4070000),
  (2023, 'Motorcycle',              2510000000000, 360000000000, 18500000),
  (2023, 'Financial Services',       1100000000000, 180000000000,     NULL),
  (2023, 'Power Products & Other',    400000000000,  24000000000,     NULL);

CREATE OR REPLACE TABLE cs4603.pa4.meridian_income_statement (
  fiscal_year INT NOT NULL COMMENT 'Fiscal year ending March 31, expressed as a four-digit year.',
  display_order INT NOT NULL COMMENT 'Presentation order in the condensed statement of operations.',
  line_item STRING NOT NULL COMMENT 'Consolidated income-statement line item.',
  amount_yen BIGINT NOT NULL COMMENT 'Amount in raw Japanese yen; costs and expenses are negative.'
)
USING DELTA
COMMENT 'Meridian condensed consolidated statement of operations for FY2022-FY2023.';

-- The 26 source rows are maintained in genie/build_tables.py to give the local
-- CLI one idempotent implementation and keep validation evidence reproducible.

-- Trusted query 1: FY2023 segment revenue ranking.
SELECT segment, revenue_yen / 1000000000.0 AS revenue_billion_yen
FROM cs4603.pa4.meridian_segment_financials
WHERE fiscal_year = 2023
ORDER BY revenue_yen DESC;

-- Trusted query 2: segment year-over-year revenue growth.
SELECT current.segment,
       prior.revenue_yen / 1000000000.0 AS fy2022_revenue_billion_yen,
       current.revenue_yen / 1000000000.0 AS fy2023_revenue_billion_yen,
       (current.revenue_yen - prior.revenue_yen) * 100.0
         / prior.revenue_yen AS yoy_growth_pct
FROM cs4603.pa4.meridian_segment_financials current
JOIN cs4603.pa4.meridian_segment_financials prior
  ON current.segment = prior.segment
WHERE current.fiscal_year = 2023 AND prior.fiscal_year = 2022
ORDER BY yoy_growth_pct DESC;
