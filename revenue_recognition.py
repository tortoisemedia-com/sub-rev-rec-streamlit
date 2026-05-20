from __future__ import annotations

import io
import re
from typing import BinaryIO, Iterable

import pandas as pd


REQUIRED_APPLE_COLUMNS = {
    "Start Date",
    "End Date",
    "Vendor Identifier",
    "Quantity",
    "Partner Share",
    "Extended Partner Share",
    "Partner Share Currency",
    "Sales or Return",
    "Title",
    "Country Of Sale",
    "Customer Price",
    "Customer Currency",
}

TEMPLATE_CURRENCY_ORDER = [
    "AED",
    "AUD",
    "CAD",
    "CHF",
    "CNY",
    "DKK",
    "EUR",
    "GBP",
    "HKD",
    "HUF",
    "ILS",
    "JPY",
    "NOK",
    "NZD",
    "PEN",
    "PLN",
    "QAR",
    "RON",
    "RUB",
    "SEK",
    "SGD",
    "THB",
    "TRY",
    "USD",
]

# GBP per 1 unit of currency. Defaults are a static snapshot from Frankfurter
# latest rates fetched on 2026-05-20, then editable in the app.
DEFAULT_FX_RATES_GBP = {
    "AED": 0.20319008,
    "AUD": 0.53084192,
    "BGN": 0.44283057,
    "BHD": 1.98459951,
    "BRL": 0.14851559,
    "CAD": 0.54256416,
    "CHF": 0.94535829,
    "CLP": 0.00082725,
    "CNY": 0.10964792,
    "COP": 0.00019857,
    "CZK": 0.03563792,
    "DKK": 0.11594875,
    "EGP": 0.01402367,
    "EUR": 0.86610081,
    "GBP": 1.0,
    "GHS": 0.06487945,
    "HKD": 0.09515563,
    "HUF": 0.00239958,
    "IDR": 0.00004220,
    "ILS": 0.25571524,
    "INR": 0.00771903,
    "ISK": 0.00604047,
    "JOD": 1.05248755,
    "JPY": 0.00468867,
    "KES": 0.00575871,
    "KRW": 0.00049555,
    "KWD": 2.42624224,
    "KZT": 0.00158441,
    "MAD": 0.08082310,
    "MXN": 0.04301445,
    "MYR": 0.18778990,
    "NGN": 0.00054308,
    "NOK": 0.08043823,
    "NZD": 0.43622404,
    "OMR": 1.94073010,
    "PEN": 0.21820721,
    "PHP": 0.01209044,
    "PKR": 0.00267766,
    "PLN": 0.20393181,
    "QAR": 0.20500205,
    "RON": 0.16567263,
    "RUB": 0.01046025,
    "SAR": 0.19898914,
    "SEK": 0.07947294,
    "SGD": 0.58264872,
    "THB": 0.02283992,
    "TRY": 0.01637144,
    "TWD": 0.02357434,
    "UAH": 0.01688847,
    "USD": 0.74621297,
    "VND": 0.00002843,
    "ZAR": 0.04490346,
}


class AppleReportError(ValueError):
    """Raised when an uploaded Apple report cannot be parsed safely."""


def _decode_report_bytes(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise AppleReportError("Could not decode file as text.")


def infer_report_month(filename: str) -> str | None:
    """Infer YYYY-MM from Apple names such as 88085216_0426_GB.txt."""
    match = re.search(r"_(\d{2})(\d{2})(?:_|\.|$)", filename)
    if not match:
        return None
    month = int(match.group(1))
    year = 2000 + int(match.group(2))
    if not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def parse_apple_report(file_obj: BinaryIO | bytes, filename: str) -> pd.DataFrame:
    raw = file_obj if isinstance(file_obj, bytes) else file_obj.read()
    if not raw:
        raise AppleReportError(f"{filename}: uploaded file is empty.")

    text = _decode_report_bytes(raw)
    try:
        df = pd.read_csv(io.StringIO(text), sep="\t", dtype=str, keep_default_na=False)
    except Exception as exc:  # pragma: no cover - pandas error details vary.
        raise AppleReportError(f"{filename}: could not read tab-delimited Apple report.") from exc

    missing = sorted(REQUIRED_APPLE_COLUMNS.difference(df.columns))
    if missing:
        raise AppleReportError(f"{filename}: missing required columns: {', '.join(missing)}.")

    df = df.loc[~df["Start Date"].str.startswith("Total_", na=False)].copy()
    df = df.loc[df["Title"].str.strip().ne("") | df["Vendor Identifier"].str.strip().ne("")]
    if df.empty:
        raise AppleReportError(f"{filename}: no subscription detail rows found.")

    numeric_columns = ["Quantity", "Partner Share", "Extended Partner Share", "Customer Price"]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if df["Extended Partner Share"].isna().any():
        bad_count = int(df["Extended Partner Share"].isna().sum())
        raise AppleReportError(
            f"{filename}: {bad_count} rows have invalid Extended Partner Share values."
        )

    df["Source File"] = filename
    df["Report Month"] = infer_report_month(filename)
    df["Currency"] = (
        df["Partner Share Currency"].str.strip().str.upper().replace("", pd.NA)
    )
    df["Currency"] = df["Currency"].fillna(df["Customer Currency"].str.strip().str.upper())
    return df.reset_index(drop=True)


def parse_many_reports(files: Iterable[tuple[str, BinaryIO | bytes]]) -> tuple[pd.DataFrame, list[str]]:
    frames: list[pd.DataFrame] = []
    errors: list[str] = []
    for filename, file_obj in files:
        try:
            frames.append(parse_apple_report(file_obj, filename))
        except AppleReportError as exc:
            errors.append(str(exc))

    if not frames:
        return pd.DataFrame(), errors
    return pd.concat(frames, ignore_index=True), errors


def classify_plan(row: pd.Series) -> tuple[str, str]:
    title = str(row.get("Title", "")).lower()
    vendor = str(row.get("Vendor Identifier", "")).lower()
    haystack = f"{title} {vendor}"

    revenue_group = "Legacy (Tortoise)" if "tortoise" in haystack else "New Observer"

    if any(token in haystack for token in ("annual", "1year", "yearly", "year")):
        billing_period = "Annual"
    elif any(token in haystack for token in ("monthly", "1month", "month")):
        billing_period = "Monthly"
    else:
        billing_period = "Unclassified"

    return revenue_group, billing_period


def enrich_transactions(df: pd.DataFrame, fx_rates: dict[str, float]) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    enriched = df.copy()
    classifications = enriched.apply(classify_plan, axis=1, result_type="expand")
    enriched["Revenue Group"] = classifications[0]
    enriched["Billing Period"] = classifications[1]
    enriched["FX Rate to GBP"] = enriched["Currency"].map(fx_rates)
    enriched["Recognised GBP"] = enriched["Extended Partner Share"] * enriched["FX Rate to GBP"]
    return enriched


def missing_fx_currencies(df: pd.DataFrame, fx_rates: dict[str, float]) -> list[str]:
    if df.empty or "Currency" not in df:
        return []
    currencies = set(df["Currency"].dropna().astype(str).str.upper())
    return sorted(currency for currency in currencies if currency not in fx_rates)


def build_summary_report(
    transactions: pd.DataFrame,
    currency_order: list[str] | None = None,
) -> pd.DataFrame:
    columns = [
        "Currency",
        "Legacy Monthly",
        "Legacy Annual",
        "Legacy Total",
        "New Observer Monthly",
        "New Observer Annual",
        "New Observer Total",
        "Total Monthly",
        "Total Annual",
        "Total Revenue",
    ]
    if transactions.empty:
        return pd.DataFrame(columns=columns)

    reportable = transactions.loc[transactions["Billing Period"].isin(["Monthly", "Annual"])].copy()
    order = currency_order or TEMPLATE_CURRENCY_ORDER
    used_currencies = sorted(reportable["Currency"].dropna().unique().tolist())
    ordered_currencies = [currency for currency in order if currency in set(order).union(used_currencies)]
    ordered_currencies.extend(currency for currency in used_currencies if currency not in ordered_currencies)

    rows = [_summary_row(reportable, "GBP (ALL)", value_column="Recognised GBP")]
    for currency in ordered_currencies:
        currency_df = reportable.loc[reportable["Currency"].eq(currency)]
        rows.append(_summary_row(currency_df, currency, value_column="Extended Partner Share"))

    summary = pd.DataFrame(rows, columns=columns)
    amount_columns = [column for column in columns if column != "Currency"]
    summary[amount_columns] = summary[amount_columns].fillna(0.0).round(2)
    return summary


def _summary_row(df: pd.DataFrame, label: str, value_column: str) -> dict[str, float | str]:
    legacy_monthly = _sum(df, "Legacy (Tortoise)", "Monthly", value_column)
    legacy_annual = _sum(df, "Legacy (Tortoise)", "Annual", value_column)
    observer_monthly = _sum(df, "New Observer", "Monthly", value_column)
    observer_annual = _sum(df, "New Observer", "Annual", value_column)
    return {
        "Currency": label,
        "Legacy Monthly": legacy_monthly,
        "Legacy Annual": legacy_annual,
        "Legacy Total": legacy_monthly + legacy_annual,
        "New Observer Monthly": observer_monthly,
        "New Observer Annual": observer_annual,
        "New Observer Total": observer_monthly + observer_annual,
        "Total Monthly": legacy_monthly + observer_monthly,
        "Total Annual": legacy_annual + observer_annual,
        "Total Revenue": legacy_monthly + legacy_annual + observer_monthly + observer_annual,
    }


def _sum(df: pd.DataFrame, group: str, billing_period: str, value_column: str) -> float:
    if df.empty:
        return 0.0
    mask = df["Revenue Group"].eq(group) & df["Billing Period"].eq(billing_period)
    return float(df.loc[mask, value_column].sum())


def build_fx_editor_frame(fx_rates: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"Currency": list(fx_rates.keys()), "GBP per unit": list(fx_rates.values())}
    ).sort_values("Currency", ignore_index=True)


def fx_frame_to_dict(fx_frame: pd.DataFrame) -> dict[str, float]:
    cleaned = fx_frame.copy()
    cleaned["Currency"] = cleaned["Currency"].astype(str).str.strip().str.upper()
    cleaned["GBP per unit"] = pd.to_numeric(cleaned["GBP per unit"], errors="coerce")
    cleaned = cleaned.loc[cleaned["Currency"].ne("") & cleaned["GBP per unit"].gt(0)]
    return dict(zip(cleaned["Currency"], cleaned["GBP per unit"]))
