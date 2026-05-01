"""
Shopify Subscription Apps — Negative Review Monitor
- Monitors 1-star and 2-star reviews across all competitor apps
- Sends Slack alerts for new negative reviews
- State persisted via GitHub Actions cache (review_state.json)
- Date-aware: parses review dates, skips old reviews, early-exits per page
- No Selenium — pure requests + BeautifulSoup
"""

import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# ── Config ───────────────────────────────────────────────────
SLACK_WEBHOOK_URL       = os.environ.get("SLACK_WEBHOOK_URL", "")
STATE_FILE              = os.environ.get("STATE_FILE", "review_state.json")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
GOOGLE_SHEET_ID         = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SHEET_TAB        = os.environ.get("GOOGLE_SHEET_TAB", "Negative Reviews")
WATCH_RATINGS           = [1, 2]

# Only alert on reviews newer than this date.
# On first run, this acts as a hard cutoff — no spam from old reviews.
# Format: YYYY-MM-DD
ALERT_CUTOFF_DATE = datetime(2026, 2, 28, tzinfo=timezone.utc)

# All competitor apps to monitor (slug → display name)
APPS = {
    "subscription-payments":        "Recharge Subscriptions",
    "shopify-subscriptions":        "Shopify Subscriptions",
    "kaching-subscriptions":        "Kaching Subscriptions",
    "subscribfy":                   "Subscribfy",
    "seal-subscriptions":           "Seal Subscriptions",
    "subscriptions-by-appstle":     "Appstle Subscriptions",
    "joy-subscription":             "Joy Subscriptions",
    "easy-subscription":            "Easy Subscription",
    "subscription-recurring-pay":   "Subscription Recurring Pay",
    "recurring-order-subscription": "Recurring Order & Subscription",
    "recurpay-subscriptions":       "RecurPay Subscriptions",
    "skio":                         "Skio",
    "ego-subscriptions":            "Ego Subscriptions",
    "stayai-subscriptions":         "Stay AI Subscriptions",
    "bony-subscriptions-app":       "Bony Subscriptions",
    "bold-subscriptions":           "Bold Subscriptions",
    "recurring-invoices":           "Recurring Invoices",
}

SHOPIFY_BASE = "https://apps.shopify.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Month name → number map for date parsing
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
# ─────────────────────────────────────────────────────────────


# ════════════════════════════════════════════
#  DATE PARSING
# ════════════════════════════════════════════

def parse_review_date(date_str: str) -> datetime | None:
    """
    Parse Shopify review date strings like:
    - "June 3, 2024"
    - "Edited July 9, 2024"
    - "September 29, 2022"
    Returns UTC-aware datetime or None if unparseable.
    """
    if not date_str:
        return None

    # Strip "Edited " prefix if present
    cleaned = re.sub(r"^edited\s+", "", date_str.strip(), flags=re.IGNORECASE)

    # Match "Month Day, Year"
    match = re.search(
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+(\d{1,2}),?\s+(\d{4})",
        cleaned, re.IGNORECASE
    )
    if not match:
        return None

    try:
        month = MONTH_MAP[match.group(1).lower()]
        day   = int(match.group(2))
        year  = int(match.group(3))
        return datetime(year, month, day, tzinfo=timezone.utc)
    except (ValueError, KeyError):
        return None


def is_new_enough(date_str: str) -> bool:
    """Returns True if review date is after ALERT_CUTOFF_DATE."""
    dt = parse_review_date(date_str)
    if dt is None:
        return True  # if unparseable, don't silently skip — let it through
    return dt > ALERT_CUTOFF_DATE


# ════════════════════════════════════════════
#  STATE
# ════════════════════════════════════════════

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
                print(f"[STATE] Loaded {len(state)} app entries.")
                return state
        except (json.JSONDecodeError, IOError) as e:
            print(f"[STATE] Corrupt/unreadable: {e}. Starting fresh.")
    print("[STATE] No state found. First run.")
    return {}


def save_state(state: dict):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=4)
        print(f"[STATE] Saved -> {STATE_FILE}")
    except IOError as e:
        print(f"[STATE] Failed to save: {e}")


def get_app_state(state: dict, slug: str, rating: int) -> dict:
    return state.get(slug, {}).get(str(rating), {"count": 0, "last_id": None})


def set_app_state(state: dict, slug: str, rating: int, data: dict):
    if slug not in state:
        state[slug] = {}
    state[slug][str(rating)] = data


# ════════════════════════════════════════════
#  SLACK
# ════════════════════════════════════════════

RATING_EMOJI = {1: "🚨", 2: "⚠️"}
RATING_LABEL = {1: "1-Star", 2: "2-Star"}


def send_slack(message: str):
    if not SLACK_WEBHOOK_URL:
        print("[SLACK] Webhook not set. Message:\n" + message)
        return
    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)
        if resp.status_code != 200:
            print(f"[SLACK] Error {resp.status_code}: {resp.text}")
        else:
            print("[SLACK] Sent.")
    except Exception as e:
        print(f"[SLACK] Request failed: {e}")


def build_slack_message(review: dict, app_name: str) -> str:
    emoji   = RATING_EMOJI.get(review["rating"], "⚠️")
    label   = RATING_LABEL.get(review["rating"], f"{review['rating']}-Star")
    preview = review["text"][:300] + "..." if len(review["text"]) > 300 else review["text"]

    return (
        f"{emoji} *New {label} Review — {app_name}* {emoji}\n\n"
        f"*Store:* {review['store']}\n"
        f"*Date:* {review['date']}\n"
        f"*Review:* {preview}\n"
        f"*Link:* {review['link']}"
    )


# ════════════════════════════════════════════
#  GOOGLE SHEETS
# ════════════════════════════════════════════

SHEET_HEADER = ["App", "Rating", "Store", "Review Date", "Review Text", "Link", "Timestamp"]

_sheet_handle = None  # cached worksheet


def get_sheet():
    """Lazy-init worksheet. Returns None if credentials missing or auth fails."""
    global _sheet_handle
    if _sheet_handle is not None:
        return _sheet_handle

    if not GOOGLE_CREDENTIALS_JSON or not GOOGLE_SHEET_ID:
        print("[SHEETS] Credentials or sheet ID not set. Skipping Sheets logging.")
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)

        try:
            ws = spreadsheet.worksheet(GOOGLE_SHEET_TAB)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=GOOGLE_SHEET_TAB, rows=1000, cols=len(SHEET_HEADER))
            ws.append_row(SHEET_HEADER, value_input_option="USER_ENTERED")
            print(f"[SHEETS] Created tab '{GOOGLE_SHEET_TAB}' with header.")

        # Ensure header exists (in case tab was created manually and is empty)
        first_row = ws.row_values(1)
        if not first_row:
            ws.append_row(SHEET_HEADER, value_input_option="USER_ENTERED")

        _sheet_handle = ws
        print(f"[SHEETS] Connected to '{GOOGLE_SHEET_TAB}'.")
        return ws
    except Exception as e:
        print(f"[SHEETS] Auth/connect failed: {e}")
        return None


def append_to_sheet(review: dict, app_name: str):
    ws = get_sheet()
    if ws is None:
        return
    row = [
        app_name,
        review["rating"],
        review["store"],
        review["date"],
        review["text"],
        review["link"],
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    ]
    try:
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"[SHEETS] Logged review {review['id']}")
    except Exception as e:
        print(f"[SHEETS] Append failed for {review['id']}: {e}")


# ════════════════════════════════════════════
#  HTTP
# ════════════════════════════════════════════

def fetch_html(url: str, params: dict = None, retries: int = 3) -> str | None:
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 429:
                wait = 15 * attempt
                print(f"[HTTP] 429 rate limit. Waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"[HTTP] {resp.status_code} on attempt {attempt} — {url}")
                time.sleep(5 * attempt)
        except Exception as e:
            print(f"[HTTP] Error (attempt {attempt}): {e}")
            time.sleep(5 * attempt)
    return None


# ════════════════════════════════════════════
#  SCRAPING
# ════════════════════════════════════════════

def clean_count(s: str) -> int:
    s = s.strip().lower().replace(",", "")
    if "k" in s:
        return int(float(s.replace("k", "")) * 1000)
    return int(s) if s.isdigit() else 0


def get_review_count(slug: str, rating: int) -> int | None:
    html = fetch_html(f"{SHOPIFY_BASE}/{slug}")
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    el = soup.select_one(f'a[href*="ratings%5B%5D={rating}"] span.link-block--underline')
    if el:
        return clean_count(el.get_text(strip=True))

    fallback = soup.find("a", attrs={"aria-label": re.compile(rf"{rating}\s*star", re.I)})
    if fallback:
        match = re.search(r"[\d,]+", fallback.get_text())
        if match:
            return clean_count(match.group())

    print(f"[COUNT] Could not find count for {slug} ★{rating}")
    return None


def get_new_reviews(slug: str, rating: int, last_known_id: str | None) -> tuple[list[dict], str | None]:
    """
    Fetch new reviews for a given app + rating.
    - Sorted by newest first.
    - Stops at last_known_id (already seen).
    - Also stops early if review date goes older than ALERT_CUTOFF_DATE.
    - Returns (new_reviews_oldest_first, new_latest_id).
    """
    review_url = f"{SHOPIFY_BASE}/{slug}/reviews"
    html = fetch_html(review_url, params={"ratings[]": rating, "sort_by": "newest"})
    if not html:
        return [], last_known_id

    soup = BeautifulSoup(html, "html.parser")

    review_divs = soup.find_all("div", attrs={"data-merchant-review": ""})
    if not review_divs:
        review_divs = soup.find_all("div", attrs={"data-review-content-id": True})

    if not review_divs:
        print(f"  [★{rating}] No review elements found for {slug}")
        return [], last_known_id

    first_div     = review_divs[0]
    new_latest_id = (
        first_div.get("data-review-content-id")
        or _extract_review_id(first_div)
    )

    print(f"  [★{rating}] Latest ID: {new_latest_id} | Known: {last_known_id}")

    if new_latest_id == last_known_id:
        return [], last_known_id

    new_reviews  = []
    hit_old_date = False

    for div in review_divs:
        rid = div.get("data-review-content-id") or _extract_review_id(div)

        # Stop at already-seen review
        if rid == last_known_id:
            print(f"  [★{rating}] Hit last known ID. Stopping.")
            break

        review = _parse_review(div, rid, rating)
        if not review:
            continue

        # Early exit: once dates go older than cutoff, no point continuing
        if not is_new_enough(review["date"]):
            print(f"  [★{rating}] Review {rid} dated '{review['date']}' is before cutoff. Stopping.")
            hit_old_date = True
            break

        new_reviews.append(review)

    if hit_old_date and not new_reviews:
        # All reviews on page are old — don't reset last_id
        return [], last_known_id

    return list(reversed(new_reviews)), new_latest_id


def _extract_review_id(div) -> str | None:
    parent = div.find_parent("div", attrs={"id": re.compile(r"review-\d+")})
    if parent:
        return parent["id"].replace("review-", "")
    return None


def _parse_review(div, review_id: str, rating: int) -> dict | None:
    try:
        store_span = div.find("span", attrs={"title": True})
        store_name = store_span["title"] if store_span else "Unknown Store"

        date_el = div.find(
            "div", class_=lambda c: c and "tw-text-fg-tertiary" in c and "tw-text-body-xs" in c
        )
        date = date_el.get_text(strip=True) if date_el else ""

        content_el = div.find("div", attrs={"data-truncate-content-copy": True})
        text = content_el.get_text(separator=" ", strip=True) if content_el else "N/A"

        return {
            "id":     review_id,
            "store":  store_name,
            "date":   date,
            "text":   text,
            "rating": rating,
            "link":   f"https://apps.shopify.com/reviews/{review_id}" if review_id else SHOPIFY_BASE,
        }
    except Exception as e:
        print(f"[PARSE] Error on review {review_id}: {e}")
        return None


# ════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════

def main():
    print(f"{'='*60}")
    print(f"  Shopify Subscription Monitor — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"  Tracking {len(APPS)} apps x {len(WATCH_RATINGS)} ratings")
    print(f"  Alert cutoff: {ALERT_CUTOFF_DATE.strftime('%Y-%m-%d')}")
    print(f"{'='*60}\n")

    state     = load_state()
    total_new = 0

    for slug, app_name in APPS.items():
        print(f"\n── {app_name} ({slug}) ──")

        for rating in WATCH_RATINGS:
            current_count = get_review_count(slug, rating)
            if current_count is None:
                print(f"  [★{rating}] Could not fetch count. Skipping.")
                continue

            app_st      = get_app_state(state, slug, rating)
            saved_count = app_st["count"]
            last_id     = app_st["last_id"]

            print(f"  [★{rating}] saved={saved_count} | current={current_count}")

            # Always persist latest count
            set_app_state(state, slug, rating, {"count": current_count, "last_id": last_id})

            if current_count <= saved_count and last_id is not None:
                print(f"  [★{rating}] No new reviews.")
                time.sleep(1)
                continue

            new_reviews, new_latest_id = get_new_reviews(slug, rating, last_id)

            set_app_state(state, slug, rating, {
                "count":   current_count,
                "last_id": new_latest_id or last_id,
            })

            if not new_reviews:
                if last_id is None:
                    print(f"  [★{rating}] First run — baseline set. No alerts (cutoff active).")
                else:
                    print(f"  [★{rating}] Count changed but no new reviews after cutoff.")
                time.sleep(1)
                continue

            print(f"  [★{rating}] {len(new_reviews)} new review(s) -> Slack")
            total_new += len(new_reviews)

            for review in new_reviews:
                send_slack(build_slack_message(review, app_name))
                append_to_sheet(review, app_name)
                time.sleep(1)

        time.sleep(2)  # Polite gap between apps

    save_state(state)

    print(f"\n{'='*60}")
    print(f"  Done! Total new alerts sent: {total_new}")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}")

    if total_new == 0:
        send_slack(
            f"✅ *Monitor Heartbeat* — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"All {len(APPS)} apps checked. No new ★1/★2 reviews found."
        )


if __name__ == "__main__":
    main()
