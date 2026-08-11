"""
Phase 1 data pipeline: reconstructs historical S&P 500 membership
(survivorship-bias-free) and downloads split/dividend-adjusted daily OHLCV
for every historical constituent, storing both in stocks.db.

Consolidated from USProjectTester.ipynb after the exploratory/debugging pass
documented in docs/research_log.md. Running build_database() reproduces the
final, already-corrected database in one shot.
"""

import sqlite3
from datetime import date

import pandas as pd
import yfinance as yf

DB_PATH = "stocks.db"

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Wikipedia's index-changes table doesn't cleanly record these as "Removed"
# events -- they're ticker renames/successor listings, not real S&P exits.
# Real historical dates below (see docs/research_log.md, 2026-08-10 entry).
RENAME_END_DATES = {
    "JOYG": "2017-04-28",  # Joy Global acquired by Komatsu
    "KORS": "2018-12-03",  # Michael Kors Holdings renamed Capri Holdings (CPRI)
    "LUK": "2018-03-01",  # Leucadia National renamed Jefferies Financial Group (JEF)
    "TSO": "2017-08-01",  # Tesoro Corp renamed Andeavor (ANDV)
    "WLP": "2014-12-03",  # WellPoint Inc renamed Anthem Inc (ANTM)
}

# Confirmed bad data sources -- excluded from both tables entirely rather than
# left in as silent corruption. See docs/research_log.md, 2026-08-08 entry.
# NCC: ticker shared by multiple unrelated companies; yfinance returns a
#      blended/mismatched series under this symbol.
# CPWR: price levels inconsistent with the real company's known history.
EXCLUDED_TICKERS = {"NCC", "CPWR"}


def create_tables(cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tickers (
            Ticker TEXT,
            Date TEXT,
            Open REAL,
            High REAL,
            Low REAL,
            Close REAL,
            Volume REAL,
            PRIMARY KEY (Ticker, Date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS membership (
            Ticker TEXT,
            Start_Date TEXT,
            End_Date TEXT,
            PRIMARY KEY (Ticker, Start_Date)
        )
    """)


def reconstruct_membership(cursor):
    """Walks Wikipedia's Added/Removed event history in chronological order
    to reconstruct historical S&P 500 membership intervals."""
    tables = pd.read_html(WIKIPEDIA_URL, storage_options={"User-Agent": USER_AGENT})
    changes = tables[1]
    changes.columns = [
        col[0] if col[0] == col[1] else " ".join(col) for col in changes.columns
    ]
    changes["Effective Date"] = pd.to_datetime(changes["Effective Date"])
    changes = changes.sort_values("Effective Date", ascending=True)

    active_tickers = {}
    completed_intervals = []
    for _, row in changes.iterrows():
        if not pd.isna(row["Added Ticker"]):
            active_tickers[row["Added Ticker"]] = row["Effective Date"]
        if not pd.isna(row["Removed Ticker"]):
            removed = row["Removed Ticker"]
            if removed in active_tickers:
                completed_intervals.append(
                    (removed, active_tickers.pop(removed), row["Effective Date"])
                )
            else:
                print(f"Skipping {removed}: no recorded 'Added' event in this table")

    # Tickers still active at the end (never removed) get an open-ended stint.
    for ticker, start_date in active_tickers.items():
        completed_intervals.append((ticker, start_date, None))

    cleaned = []
    for ticker, start_date, end_date in completed_intervals:
        if ticker in EXCLUDED_TICKERS:
            continue
        if ticker in RENAME_END_DATES:
            end_date_str = RENAME_END_DATES[ticker]
        else:
            end_date_str = end_date.strftime("%Y-%m-%d") if end_date is not None else None
        cleaned.append((ticker, start_date.strftime("%Y-%m-%d"), end_date_str))

    cursor.execute("DELETE FROM membership")
    cursor.executemany(
        "INSERT INTO membership (Ticker, Start_Date, End_Date) VALUES (?, ?, ?)",
        cleaned,
    )
    print(f"{len(cleaned)} membership records reconstructed")


def download_ohlcv(cursor):
    """Downloads adjusted OHLCV for every membership ticker, bounded by that
    ticker's own Start_Date/End_Date so delisted tickers stop where they should."""
    cursor.execute("DELETE FROM tickers")
    cursor.execute("SELECT DISTINCT Ticker, Start_Date, End_Date FROM membership")
    constituents = cursor.fetchall()

    failed_tickers = []
    for ticker, start_date, end_date in constituents:
        try:
            end = end_date if end_date else date.today().strftime("%Y-%m-%d")
            price_data = yf.download(ticker, start=start_date, end=end, auto_adjust=True)

            if price_data.empty:
                failed_tickers.append(ticker)
                continue

            price_data = price_data.reset_index()
            price_data.columns = price_data.columns.droplevel("Ticker")
            price_data["Ticker"] = ticker
            price_data["Date"] = price_data["Date"].dt.strftime("%Y-%m-%d")

            rows = list(
                price_data[["Ticker", "Date", "Open", "High", "Low", "Close", "Volume"]]
                .itertuples(index=False, name=None)
            )
            cursor.executemany(
                "INSERT INTO tickers (Ticker, Date, Open, High, Low, Close, Volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
        except Exception as e:
            failed_tickers.append(ticker)
            print(f"{ticker} failed: {e}")

    print(f"{len(failed_tickers)} tickers failed (no data available): {failed_tickers}")


def build_database():
    connection = sqlite3.connect(DB_PATH)
    cursor = connection.cursor()
    try:
        create_tables(cursor)
        reconstruct_membership(cursor)
        connection.commit()
        download_ohlcv(cursor)
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    build_database()
