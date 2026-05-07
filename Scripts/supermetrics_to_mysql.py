"""
supermetrics_to_mysql.py
Pulls daily ad spend from all Supermetrics platforms and loads into MySQL.
Splits large date ranges into 30-day chunks to avoid API timeouts.
"""

import os
import json
import logging
import requests
import time
from datetime import date, timedelta
import mysql.connector
from mysql.connector import Error

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "supermetrics_sync.log"),
            encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── Config (hardcoded) ────────────────────────────────────────────────────────
SUPERMETRICS_API_KEY = "api_M0F_3emQE1KHc4wFOsO1lWYw_br4RQ0iORs7CyTGNNiM0_iz9X_0hfhLPE4QxMvYPOfg9d2SKxFqECxbH2rdioILmK9i41NdBw3X"
SUPERMETRICS_API_URL = "https://api.supermetrics.com/enterprise/v2/query/data/json"

MYSQL_HOST     = "mysql-bi-g.cyrjbg1j8gup.us-east-1.rds.amazonaws.com"
MYSQL_PORT     = 3306
MYSQL_DB       = "mysql_bi_g"
MYSQL_USER     = "alex.metzen"
MYSQL_PASSWORD = "!4*4OwaW"

# Days back to pull. 1 = yesterday only (for daily scheduling).
# Set higher for backfill (e.g. 454). Large ranges are auto-chunked below.
DAYS_BACK = 454

# Maximum days per API request. 30 is safe for all platforms.
CHUNK_DAYS = 30

# Seconds to wait between chunks to avoid rate limiting
CHUNK_SLEEP = 2

# ── Platform definitions ──────────────────────────────────────────────────────
PLATFORMS = [
    {
        "name":             "Google Ads",
        "ds_id":            "AW",
        "ds_accounts":      ",".join([
            "7583204052", "7899758362", "9836861295", "9379912052",
            "5767903547", "7915909984", "8765950045", "5923558288",
            "7875019780", "3544148386", "9745008239", "7116548735",
            "7797353660", "3309961547", "3484300952", "2051502544",
            "5630658582", "6497802601", "7631184237", "5117429941",
            "8659161490", "4754515480", "9495619300", "6895867809",
            "7079143646", "1598139807", "8120247354",
        ]),
        "date_field":       "Date",
        "account_field":    "Accountname_fromAW",
        "account_id_field": "profileID",
        "currency_field":   "Currencycode",
        "spend_field":      "Cost",
        "settings":         {"exclude_invalid_accounts": True},
    },
    {
        "name":             "Facebook Ads",
        "ds_id":            "FA",
        "ds_accounts":      ",".join([
            "act_10151423837042487", "act_771660696001174", "act_1064688407229793",
            "act_278467619790311",   "act_566243390692640", "act_351009029477640",
            "act_382746066483377",   "act_130788325604271", "act_823811591907447",
            "act_270891901374771",   "act_590100372347659", "act_422701040006018",
            "act_886044262601259",   "act_1293015748793681","act_1173764477259489",
            "act_972923621452567",   "act_1925631788332572","act_4227974700756940",
            "act_1242489267983261",  "act_1585264516014364","act_282743365099659",
            "act_120209814738820",   "act_1602393436473859","act_730863273919592",
            "act_203877260536608",   "act_398504270823583", "act_451584522392432",
            "act_208048160248642",   "act_1042792112756096","act_318576339165729",
            "act_741258570071795",   "act_829180617881504", "act_376130836878073",
            "act_364373738243986",   "act_340559637203361", "act_369003734295473",
            "act_3218694071690285",  "act_603392587727791", "act_461660065857267",
            "act_1455289518417289",  "act_613095591537584",
        ]),
        "date_field":       "Date",
        "account_field":    "profile",
        "account_id_field": "profileID",
        "currency_field":   "currency",
        "spend_field":      "cost",
        "settings":         {},
    },
    {
        "name":             "TikTok Ads",
        "ds_id":            "TIK",
        "ds_accounts":      "7062053918607540225,7439772114296897552",
        "date_field":       "date",
        "account_field":    "advertiser_name",
        "account_id_field": "advertiser_id",
        "currency_field":   "advertiser_currency",
        "spend_field":      "cost",
        "settings":         {"report_type": "Advertiser"},
    },
    {
        "name":             "Kwai Ads",
        "ds_id":            "KWAI",
        "ds_accounts":      "65750295,77514408",
        "date_field":       "date",
        "account_field":    "account_name",
        "account_id_field": "account_id",
        "currency_field":   "account_currency",
        "spend_field":      "cost",
        "settings":         {"report_type": "basic"},
    },
]

# ── MySQL ─────────────────────────────────────────────────────────────────────
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_ad_spend (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    platform     VARCHAR(50)    NOT NULL,
    `date`       DATE           NOT NULL,
    account_id   VARCHAR(255)   NOT NULL,
    account_name VARCHAR(255),
    currency     VARCHAR(10),
    spend        DECIMAL(18,6)  NOT NULL DEFAULT 0,
    inserted_at  TIMESTAMP      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_spend (platform, `date`, account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""

REPLACE_SQL = """
REPLACE INTO daily_ad_spend
    (platform, `date`, account_id, account_name, currency, spend)
VALUES (%s, %s, %s, %s, %s, %s)
"""


def get_db_connection():
    return mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT, database=MYSQL_DB,
        user=MYSQL_USER, password=MYSQL_PASSWORD, charset="utf8mb4",
    )


def date_chunks(start_str, end_str, chunk_days):
    """Split a date range into chunks of at most chunk_days days."""
    start = date.fromisoformat(start_str)
    end   = date.fromisoformat(end_str)
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=chunk_days - 1), end)
        yield current.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d")
        current = chunk_end + timedelta(days=1)


def query_chunk(platform, start_date, end_date):
    """Query one date chunk from the Supermetrics REST API."""
    fields = ",".join([
        platform["date_field"],
        platform["account_id_field"],
        platform["account_field"],
        platform["currency_field"],
        platform["spend_field"],
    ])

    payload = {
        "ds_id":           platform["ds_id"],
        "ds_accounts":     platform["ds_accounts"],
        "date_range_type": "custom",
        "start_date":      start_date,
        "end_date":        end_date,
        "fields":          fields,
        "max_rows":        10000,
        "api_key":         SUPERMETRICS_API_KEY,
    }
    payload.update(platform.get("settings", {}))

    response = requests.get(
        SUPERMETRICS_API_URL,
        params={"json": json.dumps(payload)},
        timeout=120,
    )
    if not response.ok:
        try:
            body = response.json()
            msg = body.get("meta", {}).get("error_message") or body.get("message") or response.text
        except Exception:
            msg = response.text
        raise ValueError(f"HTTP {response.status_code}: {msg}")
    data = response.json()

    if data.get("meta", {}).get("status") != "ok":
        raise ValueError(data.get("meta", {}).get("error_message", "Unknown API error"))

    headers = data.get("data", {}).get("headers", [])
    rows    = data.get("data", {}).get("rows", [])

    if not headers or not rows:
        return []

    idx     = {h: i for i, h in enumerate(headers)}
    results = []
    for row in rows:
        try:
            raw   = row[idx[platform["spend_field"]]]
            spend = float(raw) if raw not in (None, "", "null") else 0.0
            results.append({
                "date":         row[idx[platform["date_field"]]],
                "account_id":   str(row[idx[platform["account_id_field"]]]),
                "account_name": row[idx[platform["account_field"]]],
                "currency":     row[idx[platform["currency_field"]]],
                "spend":        spend,
            })
        except (KeyError, IndexError, ValueError) as e:
            log.warning(f"  Skipping malformed row: {row} ({e})")
    return results


def query_supermetrics(platform, start_date, end_date):
    """Query all chunks for a platform and return combined rows."""
    chunks = list(date_chunks(start_date, end_date, CHUNK_DAYS))
    log.info(f"Querying {platform['name']} in {len(chunks)} chunk(s) "
             f"({start_date} to {end_date}) ...")

    all_rows = []
    for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
        log.info(f"  Chunk {i}/{len(chunks)}: {chunk_start} to {chunk_end}")
        try:
            rows = query_chunk(platform, chunk_start, chunk_end)
            all_rows.extend(rows)
            log.info(f"    {len(rows)} rows")
        except Exception as e:
            log.error(f"    Failed chunk {chunk_start} to {chunk_end}: {e}")
        if i < len(chunks):
            time.sleep(CHUNK_SLEEP)

    log.info(f"  Total: {len(all_rows)} rows from {platform['name']}.")
    return all_rows


def main():
    end   = date.today() - timedelta(days=1)
    start = end - timedelta(days=DAYS_BACK - 1)
    start_date = start.strftime("%Y-%m-%d")
    end_date   = end.strftime("%Y-%m-%d")
    log.info(f"Date range: {start_date} to {end_date} ({DAYS_BACK} days, "
             f"{CHUNK_DAYS}-day chunks)")

    all_rows = []
    for platform in PLATFORMS:
        try:
            rows = query_supermetrics(platform, start_date, end_date)
            for row in rows:
                row["platform"] = platform["name"]
            all_rows.extend(rows)
        except Exception as e:
            log.error(f"Failed to fetch {platform['name']}: {e}")

    if not all_rows:
        log.warning("No data fetched from any platform. Exiting.")
        return

    conn = cursor = None
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(CREATE_TABLE_SQL)
        log.info("Table `daily_ad_spend` ensured.")

        batch = [(r["platform"], r["date"], r["account_id"],
                  r["account_name"], r["currency"], r["spend"])
                 for r in all_rows]

        cursor.executemany(REPLACE_SQL, batch)
        conn.commit()
        log.info(f"Upserted {cursor.rowcount} rows into `daily_ad_spend`.")

    except Error as e:
        log.error(f"MySQL error: {e}")
        raise
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


if __name__ == "__main__":
    main()