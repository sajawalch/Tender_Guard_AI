# TenderGuard AI — Accuracy Report

Measured on 2026-11-18 07:59 with `gpt-4o-mini` (temperature 0).

## Synthetic (15 written tenders)

- Tenders scored: **15**
- Fields correct: **163/165 (98.8%)**

| Field | Correct | Accuracy |
|---|---|---|
| contract_value_pkr | 15/15 | 100.0% |
| bid_security_amount_pkr | 15/15 | 100.0% |
| bid_security_percent | 15/15 | 100.0% |
| liquidated_damages_rate_percent_per_day | 15/15 | 100.0% |
| liquidated_damages_cap_percent | 15/15 | 100.0% |
| advance_payment_percent | 15/15 | 100.0% |
| payment_cycle_days | 13/15 | 86.7% |
| pec_category_required | 15/15 | 100.0% |
| requires_active_taxpayer_status | 15/15 | 100.0% |
| min_years_experience_required | 15/15 | 100.0% |
| completion_period_days | 15/15 | 100.0% |

**Mismatches**

- `ST-2026-010` `payment_cycle_days`: expected `30`, got `None`
- `ST-2026-015` `payment_cycle_days`: expected `30`, got `None`

## Real PPRA tenders (confirmed fields only)

- Tenders scored: **7**
- Fields correct: **8/14 (57.1%)**
- Skipped: 3 (TS0000016240E, TS0000016188E, FW0000016210E)

| Field | Correct | Accuracy |
|---|---|---|
| contract_value_pkr | 0/1 | 0.0% |
| bid_security_amount_pkr | 2/5 | 40.0% |
| bid_security_percent | 1/3 | 33.3% |
| liquidated_damages_rate_percent_per_day | 1/1 | 100.0% |
| advance_payment_percent | 1/1 | 100.0% |
| pec_category_required | 1/1 | 100.0% |
| requires_active_taxpayer_status | 1/1 | 100.0% |
| completion_period_days | 1/1 | 100.0% |

**Mismatches**

- `TS0000016202E` `bid_security_amount_pkr`: expected `127047.0`, got `None`
- `TS0000016233E` `bid_security_percent`: expected `0.05`, got `None`
- `TS0000016164E` `bid_security_percent`: expected `5.0`, got `None`
- `TS0000015708E` `contract_value_pkr`: expected `87883000.0`, got `None`
- `TS0000015708E` `bid_security_amount_pkr`: expected `1757600.0`, got `None`
- `TS0000012705E` `bid_security_amount_pkr`: expected `1011000000.0`, got `162000000.0`

## How to read these numbers

- **Synthetic**: tenders written for testing, so every field has a known correct answer. It shows the pipeline logic works on clean documents.
- **Real**: actual PPRA PDFs. Only fields confirmed by hand are scored, so the sample is small and the result is lower than the synthetic one. Scanned PDFs, multi-tender bulletins and tables are the hard cases.
- A field correctly left empty (the tender does not state it) counts as correct.