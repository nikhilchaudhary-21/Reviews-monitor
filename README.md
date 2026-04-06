# Shopify Subscription Apps — Negative Review Monitor

Monitors 1-star and 2-star reviews across 17 competitor subscription apps on the Shopify App Store. Sends Slack alerts for new negative reviews. Runs hourly via GitHub Actions.

---

## How it works

1. Fetches review counts for each app per rating (★1, ★2)
2. Compares against saved counts from last run
3. If count increased → scrapes new reviews (sorted newest first)
4. Filters out reviews older than `ALERT_CUTOFF_DATE`
5. Sends each new review to Slack
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

### 2. Add GitHub Secret

Go to **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|--------|-------|
| `SLACK_WEBHOOK_URL` | Your Slack Incoming Webhook URL |

> Get a webhook URL from: https://api.slack.com/messaging/webhooks

### 3. Install dependencies (local testing)

```bash
pip install requests beautifulsoup4
```

### 4. Local test (no Slack)

```bash
python recharge_monitor.py
```

Slack webhook nahi set hoga toh messages console pe print honge.

### 5. Local test (with Slack)

```bash
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/xxx python recharge_monitor.py
```

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

Runs every hour via cron: `0 * * * *`

Can also be triggered manually from **Actions → Recharge Review Monitor → Run workflow**.
