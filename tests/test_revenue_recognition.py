import io
import unittest

from revenue_recognition import (
    build_summary_report,
    enrich_transactions,
    infer_report_month,
    parse_apple_report,
)


REPORT_TEXT = """Start Date\tEnd Date\tUPC\tISRC/ISBN\tVendor Identifier\tQuantity\tPartner Share\tExtended Partner Share\tPartner Share Currency\tSales or Return\tApple Identifier\tArtist/Show/Developer/Author\tTitle\tLabel/Studio/Network/Developer/Publisher\tGrid\tProduct Type Identifier\tISAN/Other Identifier\tCountry Of Sale\tPre-order Flag\tPromo Code\tCustomer Price\tCustomer Currency
03/29/2026\t05/02/2026\t\t\tcom.tortoisemedia.tortoise.sub.1month\t2\t4.00\t8.00\tGBP\tS\t1476829056\t\tTortoise Monthly Subscription\t\t\tIAY\t\tGB\t\t\t4.99\tGBP
03/29/2026\t05/02/2026\t\t\tcom.tortoisemedia.tortoise.sub.1year\t1\t80.00\t80.00\tGBP\tS\t1476826412\t\tTortoise Annual Subscription\t\t\tIAY\t\tGB\t\t\t99.99\tGBP
03/29/2026\t05/02/2026\t\t\tuk.co.observer.sub.iap.1month\t3\t10.00\t30.00\tUSD\tS\t6755604343\t\tThe Observer Monthly Subscription\t\t\tIAY\t\tUS\t\t\t15.99\tUSD
03/29/2026\t05/02/2026\t\t\tuk.co.observer.sub.iap.1year\t-1\t100.00\t-100.00\tUSD\tR\t6755604205\t\tThe Observer Annual Subscription\t\t\tIAY\t\tUS\t\t\t-143.99\tUSD
Total_Rows\t4
Total_Amount\t18.00
Total_Units\t5
"""


class RevenueRecognitionTests(unittest.TestCase):
    def test_infers_month_from_apple_filename(self):
        self.assertEqual(infer_report_month("88085216_0426_GB.txt"), "2026-04")
        self.assertIsNone(infer_report_month("88085216_9926_GB.txt"))

    def test_parses_detail_rows_and_ignores_footers(self):
        df = parse_apple_report(io.BytesIO(REPORT_TEXT.encode()), "88085216_0426_GB.txt")
        self.assertEqual(len(df), 4)
        self.assertEqual(df["Report Month"].unique().tolist(), ["2026-04"])
        self.assertEqual(float(df["Extended Partner Share"].sum()), 18.0)

    def test_builds_template_style_summary(self):
        df = parse_apple_report(io.BytesIO(REPORT_TEXT.encode()), "88085216_0426_GB.txt")
        enriched = enrich_transactions(df, {"GBP": 1.0, "USD": 0.75})
        summary = build_summary_report(enriched, currency_order=["GBP", "USD"])

        gbp_all = summary.loc[summary["Currency"].eq("GBP (ALL)")].iloc[0]
        self.assertEqual(gbp_all["Legacy Monthly"], 8.0)
        self.assertEqual(gbp_all["Legacy Annual"], 80.0)
        self.assertEqual(gbp_all["New Observer Monthly"], 22.5)
        self.assertEqual(gbp_all["New Observer Annual"], -75.0)
        self.assertEqual(gbp_all["Total Revenue"], 35.5)

        native_gbp = summary.loc[summary["Currency"].eq("GBP")].iloc[0]
        self.assertEqual(native_gbp["Total Revenue"], 88.0)

        native_usd = summary.loc[summary["Currency"].eq("USD")].iloc[0]
        self.assertEqual(native_usd["Total Revenue"], -70.0)


if __name__ == "__main__":
    unittest.main()

