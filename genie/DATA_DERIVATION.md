# Meridian structured-data derivation

All monetary values are stored as raw Japanese yen. The source report presents them in
billions, so every reported value is multiplied by `1,000,000,000` before insertion.

## `meridian_segment_financials`

FY2023 revenue and operating profit are transcribed from the report's **Segment Information**
table:

| Segment | Revenue in report (¥B) | Stored yen | Operating profit in report (¥B) | Stored yen |
|---|---:|---:|---:|---:|
| Automobile | 12,900 | 12,900,000,000,000 | 560 | 560,000,000,000 |
| Motorcycle | 2,510 | 2,510,000,000,000 | 360 | 360,000,000,000 |
| Financial Services | 1,100 | 1,100,000,000,000 | 180 | 180,000,000,000 |
| Power Products & Other | 400 | 400,000,000,000 | 24 | 24,000,000,000 |

The FY2023 Automobile and Motorcycle unit counts come from the report's company overview:
4.07 million vehicles and 18.5 million motorcycles. Unit counts are not meaningful for
Financial Services or the mixed Power Products & Other segment, so those values are `NULL`.

The report does not provide FY2022 segment-level amounts. The following values are explicitly
synthetic, plausible allocations created only to support year-over-year questions:

| Segment | Synthetic FY2022 revenue (¥B) | Synthetic FY2022 operating profit (¥B) | Units |
|---|---:|---:|---:|
| Automobile | 11,030 | 430 | 3,680,000 |
| Motorcycle | 2,120 | 310 | 17,000,000 |
| Financial Services | 1,030 | 145 | `NULL` |
| Power Products & Other | 370 | 20 | `NULL` |

Those synthetic rows sum exactly to the report's FY2022 consolidated net revenue of
¥14,550B and operating profit of ¥905B. The 3.68 million FY2022 vehicle count is reported;
the 17 million motorcycle count is synthetic.

## `meridian_income_statement`

Every FY2022 and FY2023 line item is transcribed from the report's **Consolidated Statement
of Operations**. Positive lines retain their reported sign. Cost of sales, SG&A, R&D, and
income tax expense are stored as negative values, matching the parentheses in the report.

The critical reconciliation rows are:

| Fiscal year | Net revenue | Operating profit | Net income attributable to owners |
|---|---:|---:|---:|
| FY2022 | ¥14,550B | ¥905B | ¥707B |
| FY2023 | ¥16,910B | ¥1,124B | ¥1,107B |

`Net income attributable to owners` is intentionally distinct from `Profit for the year`
(¥747B in FY2022 and ¥1,137B in FY2023), which includes non-controlling interests.
