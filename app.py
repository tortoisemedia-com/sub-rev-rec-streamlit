from __future__ import annotations

import altair as alt
import pandas as pd
from pandas.api.types import is_numeric_dtype
import streamlit as st

from revenue_recognition import (
    DEFAULT_FX_RATES_GBP,
    TEMPLATE_CURRENCY_ORDER,
    build_fx_editor_frame,
    build_summary_report,
    enrich_transactions,
    fx_frame_to_dict,
    missing_fx_currencies,
    parse_many_reports,
)


st.set_page_config(
    page_title="Apple IAP Revenue Recognition",
    layout="wide",
)


def money(value: float) -> str:
    return f"GBP {value:,.2f}"


def month_filename_part(month: str) -> str:
    return month.replace("-", "_") if month else "unassigned_month"


def reset_fx_rates() -> None:
    st.session_state["fx_editor_seed"] = build_fx_editor_frame(DEFAULT_FX_RATES_GBP)
    st.session_state["fx_editor_version"] = st.session_state.get("fx_editor_version", 0) + 1


def format_amount_frame(frame: pd.DataFrame) -> pd.DataFrame:
    formatted = frame.copy()
    amount_columns = [
        column for column in formatted.columns if is_numeric_dtype(formatted[column])
    ]
    for column in amount_columns:
        formatted[column] = formatted[column].map(lambda value: f"{value:,.2f}")
    return formatted


def show_summary_group(title: str, frame: pd.DataFrame) -> None:
    st.markdown(f"**{title}**")
    st.dataframe(
        format_amount_frame(frame),
        hide_index=True,
        width="stretch",
        height=min(560, 38 + (len(frame) + 1) * 35),
    )


st.title("Apple IAP Revenue Recognition")
st.caption(
    "Bulk upload Apple App Store Connect subscription reports, classify Legacy vs New Observer revenue, apply editable FX rates, and export a finance-ready CSV."
)

with st.sidebar:
    st.header("FX Assumptions")
    st.caption(
        "Rates are GBP per 1 unit of local currency. Defaults are a static 2026-05-20 snapshot and should be reviewed before posting journals."
    )
    if "fx_editor_seed" not in st.session_state:
        reset_fx_rates()
    st.button("Reset currencies to defaults", on_click=reset_fx_rates, width="stretch")
    edited_fx = st.data_editor(
        st.session_state["fx_editor_seed"],
        key=f"fx_editor_{st.session_state['fx_editor_version']}",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "Currency": st.column_config.TextColumn("Currency", help="ISO currency code"),
            "GBP per unit": st.column_config.NumberColumn(
                "GBP per unit",
                min_value=0.00000001,
                step=0.0001,
                format="%.8f",
            ),
        },
    )
    fx_rates = fx_frame_to_dict(edited_fx)

uploaded_files = st.file_uploader(
    "Upload Apple country reports",
    type=["txt", "tsv"],
    accept_multiple_files=True,
    help="Upload all monthly country reports together. Footer rows such as Total_Rows and Total_Amount are ignored.",
)

if not uploaded_files:
    st.info("Upload one or more Apple `.txt` reports to build the revenue recognition view.")
    with st.expander("Classification rules", expanded=True):
        st.markdown(
            """
            - `Tortoise Annual Subscription` and `Tortoise Monthly Subscription` are classified as `Legacy (Tortoise)`.
            - `The Observer Monthly Subscription`, `The Observer Annual Subscription`, and any other non-Tortoise plans are classified as `New Observer`.
            - Billing period is inferred from the title or vendor identifier using monthly/annual keywords.
            - `GBP (ALL)` is converted to GBP using the editable FX table; the `GBP` row remains native UK/GBP sales only.
            """
        )
    st.stop()

files_for_parser = [(uploaded_file.name, uploaded_file.getvalue()) for uploaded_file in uploaded_files]
raw_transactions, parse_errors = parse_many_reports(files_for_parser)

if parse_errors:
    st.error("Some files could not be processed.")
    for error in parse_errors:
        st.write(f"- {error}")

if raw_transactions.empty:
    st.stop()

inferred_months = sorted(
    month for month in raw_transactions["Report Month"].dropna().unique().tolist() if month
)
default_month = inferred_months[0] if len(inferred_months) == 1 else ""

top_cols = st.columns([1, 1, 1.4])
with top_cols[0]:
    recognition_month = st.text_input(
        "Recognition month",
        value=default_month,
        placeholder="YYYY-MM",
        help="Used as the month key in downloaded outputs. Apple payment dates are intentionally not used.",
    )
with top_cols[1]:
    st.metric("Files processed", f"{len(uploaded_files):,}")
with top_cols[2]:
    inferred_label = ", ".join(inferred_months) if inferred_months else "No month inferred from filenames"
    st.caption(f"Filename month inference: {inferred_label}")

if len(inferred_months) > 1:
    st.warning(
        "Uploaded files appear to span multiple report months. Set the recognition month explicitly before exporting."
    )

missing_fx = missing_fx_currencies(raw_transactions, fx_rates)
if missing_fx:
    st.error(
        "Missing FX rates for uploaded currencies: "
        + ", ".join(missing_fx)
        + ". Add them in the sidebar before exporting."
    )
    st.stop()

transactions = enrich_transactions(raw_transactions, fx_rates)
transactions["Recognition Month"] = recognition_month
unclassified = transactions.loc[transactions["Billing Period"].eq("Unclassified")]

used_currencies = sorted(transactions["Currency"].dropna().unique().tolist())
currency_order = TEMPLATE_CURRENCY_ORDER + [
    currency for currency in used_currencies if currency not in TEMPLATE_CURRENCY_ORDER
]
summary = build_summary_report(transactions, currency_order=currency_order)
summary.insert(0, "Recognition Month", recognition_month)

gbp_summary = summary.loc[summary["Currency"].eq("GBP (ALL)")].iloc[0]
metric_cols = st.columns(5)
metric_cols[0].metric("Total GBP", money(float(gbp_summary["Total Revenue"])))
metric_cols[1].metric("Monthly GBP", money(float(gbp_summary["Total Monthly"])))
metric_cols[2].metric("Annual GBP", money(float(gbp_summary["Total Annual"])))
metric_cols[3].metric("Legacy GBP", money(float(gbp_summary["Legacy Total"])))
metric_cols[4].metric("New Observer GBP", money(float(gbp_summary["New Observer Total"])))

if not unclassified.empty:
    st.warning(
        f"{len(unclassified):,} rows could not be classified as monthly or annual and are excluded from the matrix totals. Review the exceptions table before using the report."
    )

st.subheader("Revenue Recognition Matrix")
st.caption(
    "GBP (ALL) is the converted total across all uploaded currencies. Native-currency rows show source amounts before FX."
)
matrix_tabs = st.tabs(["Legacy", "New Observer", "Total", "Combined CSV view"])
with matrix_tabs[0]:
    show_summary_group(
        "Legacy (Tortoise)",
        summary[["Currency", "Legacy Monthly", "Legacy Annual", "Legacy Total"]],
    )
with matrix_tabs[1]:
    show_summary_group(
        "New Observer",
        summary[["Currency", "New Observer Monthly", "New Observer Annual", "New Observer Total"]],
    )
with matrix_tabs[2]:
    show_summary_group(
        "Total",
        summary[["Currency", "Total Monthly", "Total Annual", "Total Revenue"]],
    )
with matrix_tabs[3]:
    st.dataframe(
        format_amount_frame(summary),
        hide_index=True,
        width="stretch",
        height=min(680, 38 + (len(summary) + 1) * 35),
    )

chart_source = (
    transactions.loc[transactions["Billing Period"].isin(["Monthly", "Annual"])]
    .groupby(["Revenue Group", "Billing Period"], as_index=False)["Recognised GBP"]
    .sum()
)
currency_source = (
    transactions.loc[transactions["Billing Period"].isin(["Monthly", "Annual"])]
    .groupby("Currency", as_index=False)["Recognised GBP"]
    .sum()
    .sort_values("Recognised GBP", ascending=False)
)

chart_cols = st.columns([1, 1])
with chart_cols[0]:
    st.subheader("GBP Revenue by Plan Type")
    st.altair_chart(
        alt.Chart(chart_source)
        .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
        .encode(
            x=alt.X("Revenue Group:N", title=None),
            xOffset=alt.XOffset("Billing Period:N"),
            y=alt.Y("Recognised GBP:Q", title="Recognised GBP"),
            color=alt.Color(
                "Billing Period:N",
                scale=alt.Scale(range=["#222222", "#777777"]),
            ),
            tooltip=["Revenue Group", "Billing Period", alt.Tooltip("Recognised GBP:Q", format=",.2f")],
        )
        .properties(height=420)
        .configure_view(fill="#ffffff", stroke="#d9d9d9")
        .configure_axis(labelColor="#111111", titleColor="#111111", gridColor="#eeeeee")
        .configure_legend(labelColor="#111111", titleColor="#111111"),
        width="stretch",
    )

with chart_cols[1]:
    st.subheader("GBP Revenue by Currency")
    currency_chart_height = max(420, 34 * len(currency_source.head(15)) + 80)
    st.altair_chart(
        alt.Chart(currency_source.head(15))
        .mark_bar()
        .encode(
            y=alt.Y(
                "Currency:N",
                sort="-x",
                title=None,
                axis=alt.Axis(labelLimit=80, labelFontSize=14, labelOverlap=False),
            ),
            x=alt.X(
                "Recognised GBP:Q",
                title="Recognised GBP",
                axis=alt.Axis(labelFontSize=12, titleFontSize=13, format=",.0f"),
            ),
            color=alt.value("#222222"),
            tooltip=["Currency", alt.Tooltip("Recognised GBP:Q", format=",.2f")],
        )
        .properties(height=currency_chart_height)
        .configure_view(fill="#ffffff", stroke="#d9d9d9")
        .configure_axis(labelColor="#111111", titleColor="#111111", gridColor="#eeeeee"),
        width="stretch",
    )

with st.expander("Audit detail", expanded=False):
    detail_columns = [
        "Recognition Month",
        "Source File",
        "Start Date",
        "End Date",
        "Country Of Sale",
        "Currency",
        "Revenue Group",
        "Billing Period",
        "Title",
        "Vendor Identifier",
        "Sales or Return",
        "Quantity",
        "Partner Share",
        "Extended Partner Share",
        "FX Rate to GBP",
        "Recognised GBP",
        "Customer Price",
        "Customer Currency",
    ]
    st.dataframe(
        transactions[detail_columns],
        hide_index=True,
        width="stretch",
    )

if not unclassified.empty:
    with st.expander("Classification exceptions", expanded=True):
        st.dataframe(
            unclassified[
                [
                    "Source File",
                    "Country Of Sale",
                    "Currency",
                    "Title",
                    "Vendor Identifier",
                    "Extended Partner Share",
                ]
            ],
            hide_index=True,
            width="stretch",
        )

download_cols = st.columns([1, 1])
summary_csv = summary.to_csv(index=False).encode("utf-8")
detail_csv = transactions[detail_columns].to_csv(index=False).encode("utf-8")
with download_cols[0]:
    st.download_button(
        "Download summary CSV",
        data=summary_csv,
        file_name=f"apple_revenue_recognition_summary_{month_filename_part(recognition_month)}.csv",
        mime="text/csv",
        width="stretch",
        disabled=not recognition_month,
    )
with download_cols[1]:
    st.download_button(
        "Download audit detail CSV",
        data=detail_csv,
        file_name=f"apple_revenue_recognition_detail_{month_filename_part(recognition_month)}.csv",
        mime="text/csv",
        width="stretch",
        disabled=not recognition_month,
    )

if not recognition_month:
    st.caption("Downloads are disabled until a recognition month is entered.")
