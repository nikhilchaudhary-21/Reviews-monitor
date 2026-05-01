# Shopify Subscription Apps — Negative Review Monitor

Monitors 1-star and 2-star reviews across 17 competitor subscription apps on the Shopify App Store. Sends Slack alerts and logs every new negative review to a Google Sheet. Runs twice daily via GitHub Actions.

---

## How it works

1. Fetches review counts for each app per rating (★1, ★2)
2. Compares against saved counts from last run
3. If count increased → scrapes new reviews (sorted newest first)
4. Filters out reviews older than `ALERT_CUTOFF_DATE`
5. Sends each new review to Slack **and** appends a row to the Google Sheet
6. Saves state for next run

---

## Apps monitored

| App | Slug |
|-----|------|
| Recharge Subscriptions | `subscription-payments` |
| Shopify Subscriptions | `shopify-subscriptions` |
| Kaching Subscriptions | `kaching-subscriptions` |
| Subscribfy | `subscribfy` |
| Seal Subscriptions | `seal-subscriptions` |
| Appstle Subscriptions | `subscriptions-by-appstle` |
| Joy Subscriptions | `joy-subscription` |
| Easy Subscription | `easy-subscription` |
| Subscription Recurring Pay | `subscription-recurring-pay` |
| Recurring Order & Subscription | `recurring-order-subscription` |
| RecurPay Subscriptions | `recurpay-subscriptions` |
| Skio | `skio` |
| Ego Subscriptions | `ego-subscriptions` |
| Stay AI Subscriptions | `stayai-subscriptions` |
| Bony Subscriptions | `bony-subscriptions-app` |
| Bold Subscriptions | `bold-subscriptions` |
| Recurring Invoices | `recurring-invoices` |

---

## Setup

### 1. Clone the repo and add files

```
.github/
  workflows/
    recharge_monitor.yml
recharge_monitor.py
requirements.txt
```

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|--------|-------|
| `SLACK_WEBHOOK_URL` | Your Slack Incoming Webhook URL |
| `GOOGLE_CREDENTIALS_JSON` | Full contents of the Google service account JSON key file |
| `GOOGLE_SHEET_ID` | The sheet ID from `https://docs.google.com/spreadsheets/d/<ID>/edit` |

> Slack webhook: https://api.slack.com/messaging/webhooks

### 3. Google Sheets setup (one-time)

1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and enable both **Google Sheets API** and **Google Drive API**.
2. Create a **Service Account** → generate a JSON key → download it.
3. Create the destination Google Sheet, then **Share** it with the service account email (the `client_email` field in the JSON) as **Editor**.
4. Paste the full JSON contents into the `GOOGLE_CREDENTIALS_JSON` secret, and the sheet ID into `GOOGLE_SHEET_ID`.

The script auto-creates a tab named `Negative Reviews` with this header:

```
App | Rating | Store | Review Date | Review Text | Link | Timestamp
```

To use a different tab name, set the `GOOGLE_SHEET_TAB` env var.

### 4. Install dependencies (local testing)

```bash
pip install -r requirements.txt
```

### 5. Local test (no Slack, no Sheets)

```bash
python recharge_monitor.py
```

Agar `SLACK_WEBHOOK_URL` ya Sheets credentials set nahi honge, woh step skip ho jayega — script crash nahi karega.

### 6. Local test (full)

```bash
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx
export GOOGLE_CREDENTIALS_JSON="$(cat path/to/service-account.json)"
export GOOGLE_SHEET_ID=your-sheet-id
python recharge_monitor.py
```

> ⚠️ Never commit the service account JSON file. `.gitignore` already blocks `*.json` (with `review_state.json` whitelisted).

---

## State file

`review_state.json` stores the last seen review ID and count per app per rating. This prevents duplicate alerts across runs.

In GitHub Actions, state is persisted using `actions/cache`. If the cache is lost, the next run sets a new baseline — no spam.

---

## Alert cutoff

```python
ALERT_CUTOFF_DATE = datetime(2026, 2, 28, tzinfo=timezone.utc)
```

Only reviews **after** this date trigger Slack alerts. Update this value if you want to change the historical cutoff.

---

## Adding a new app to monitor

In `recharge_monitor.py`, add to the `APPS` dict:

```python
APPS = {
    ...
    "your-app-slug": "Display Name",
}
```

The slug is the part of the Shopify App Store URL after `apps.shopify.com/`.

---

## Slack message format

```
🚨 New 1-Star Review — Recharge Subscriptions 🚨

Store: Korean Fairy Skin Care
Date: July 9, 2024
Review: This app caused chaos in our store...
Link: https://apps.shopify.com/reviews/705893
```

---

## Schedule

Runs twice daily via cron: `0 0,12 * * *` (00:00 and 12:00 UTC = 05:30 AM and 05:30 PM IST).

Can also be triggered manually from **Actions → Recharge Review Monitor → Run workflow**.

---

## Google Sheet output

Each new review appends one row:

| App | Rating | Store | Review Date | Review Text | Link | Timestamp |
|-----|--------|-------|-------------|-------------|------|-----------|
| Recharge Subscriptions | 1 | Korean Fairy Skin Care | July 9, 2024 | This app caused chaos... | https://apps.shopify.com/reviews/705893 | 2026-05-01 12:00:00 UTC |

`Timestamp` is when the row was logged (UTC), not the review date.
