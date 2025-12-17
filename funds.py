import json
import pyotp
import pandas as pd
from kiteconnect import KiteConnect
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright

# -----------------------------
# Load credentials
# -----------------------------
with open("credentials.json") as f:
    ACCOUNTS = json.load(f)["accounts"]


# -----------------------------
# Generate access token
# -----------------------------
def generate_access_token(acc):
    kite = KiteConnect(api_key=acc["api_key"])
    totp = pyotp.TOTP(acc["totp_secret"]).now()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        page.goto(
            f"https://kite.zerodha.com/connect/login?v=3&api_key={acc['api_key']}"
        )

        page.fill("#userid", acc["user_id"])
        page.fill("#password", acc["password"])
        page.click('button[type="submit"]')

        page.wait_for_timeout(2000)
        page.fill('input[type="number"]', totp)

        page.wait_for_function(
            "() => window.location.href.includes('request_token=')",
            timeout=60000
        )

        redirect_url = page.url
        browser.close()

    request_token = parse_qs(urlparse(redirect_url).query)["request_token"][0]
    session = kite.generate_session(request_token, acc["api_secret"])

    return session["access_token"]


# -----------------------------
# MAIN
# -----------------------------
results = []

for acc in ACCOUNTS:
    row = {
        "silo": acc["silo"],
        "client_id": acc["client_id"],
        "holding_value": 0,
        "available_cash": 0,
        "other": 0,
        "total_acc_value": 0,
        "status": "FAILURE"
    }

    try:
        # Login
        access_token = generate_access_token(acc)
        kite = KiteConnect(api_key=acc["api_key"])
        kite.set_access_token(access_token)

        # -----------------------------
        # Margins
        # -----------------------------
        margins = kite.margins("equity")
        available = margins.get("available", {})
        utilised = margins.get("utilised", {})

        available_cash = available.get("cash", 0)
        adhoc_margin = available.get("adhoc_margin", 0)
        collateral = available.get("collateral", 0)

        exposure = utilised.get("exposure", 0)
        span = utilised.get("span", 0)
        delivery = utilised.get("delivery", 0)
        used_margin = utilised.get("debits", 0)

        other = (
            used_margin
            + adhoc_margin
            + collateral
            + exposure
            + span
            + delivery
        )

        # -----------------------------
        # Holdings
        # -----------------------------
        holdings = kite.holdings()
        holding_value = 0

        if holdings:
            df = pd.DataFrame(holdings)
            df["current_value"] = df["quantity"] * df["last_price"]
            holding_value = df["current_value"].sum()

        total_acc_value = holding_value + available_cash + other

        # -----------------------------
        # Populate row
        # -----------------------------
        row.update({
            "holding_value": round(holding_value, 2),
            "available_cash": round(available_cash, 2),
            "other": round(other, 2),
            "total_acc_value": round(total_acc_value, 2),
            "status": "SUCCESS"
        })

    except Exception as e:
        row["status"] = "FAILURE"

    results.append(row)


# -----------------------------
# Final Output Table
# -----------------------------
df_result = pd.DataFrame(
    results,
    columns=[
        "silo",
        "client_id",
        "holding_value",
        "available_cash",
        "other",
        "total_acc_value",
        "status"
    ]
)

print("\n================ ACCOUNT SUMMARY ================\n")
print(df_result)
print("\n=================================================\n")
