# Apple IAP Revenue Recognition

Streamlit tool for converting Apple App Store Connect subscription reports into a finance-ready revenue recognition matrix for Observer iOS subscriptions.

## What It Does

- Bulk uploads Apple `.txt` country reports.
- Ignores Apple footer rows such as `Total_Rows`, `Total_Amount`, and `Total_Units`.
- Classifies Tortoise plans as `Legacy (Tortoise)`.
- Classifies Observer and other non-Tortoise plans as `New Observer`.
- Splits recognised revenue into monthly and annual buckets.
- Converts local-currency cash to GBP using editable FX assumptions.
- Exports a summary CSV and audit-detail CSV.

## Run Locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## FX Rates

The app ships with editable GBP-per-local-currency defaults from a static 2026-05-20 Frankfurter snapshot. Finance should review or replace these rates before using the export for postings.

## Tests

The core parsing and aggregation logic is in `revenue_recognition.py` so it can be tested independently of Streamlit.

```bash
python -m unittest
```

