# Data Layer (Phase 1)

Summary of the data infrastructure built in Phase 1: a survivorship-bias-free, historically-reconstructed S&P 500 universe with daily OHLCV, stored in SQLite (`stocks.db`, gitignored — not checked in). Full narrative of how this was built, and every bug found along the way, is in [`research_log.md`](research_log.md); this doc is the final-state snapshot.

## Schema

**`membership`** — reconstructed historical S&P 500 index membership, from Wikipedia's index-changes table (see 2026-08-03 log entry).
- `Ticker`, `Start_Date`, `End_Date` (`NULL` = still an active constituent as of the last reconstruction pass)
- 385 rows / 384 distinct tickers, 247 currently marked still-active

**`tickers`** — daily OHLCV, via `yfinance`, `auto_adjust=True` (split/dividend-adjusted), bounded by each ticker's own `membership` window.
- `Ticker`, `Date` (`YYYY-MM-DD` text), `Open`, `High`, `Low`, `Close`, `Volume`; composite primary key `(Ticker, Date)`
- 581,612 rows across 301 tickers, spanning 1976-07-01 to 2026-08-06

## Known, explicitly-accepted limitations

These are documented exclusions, not silent gaps — carried forward into Phase 2 rather than hidden:

- **83 of 384 membership tickers have zero rows in `tickers`.** Almost entirely real M&A, bankruptcy, or delisting (e.g. `ABK`, `ALXN`, `CERN`, `ATVI`, `TWTR`, `SIVB`, `FRC`) where `yfinance` has no data under the old symbol.
- **`NCC` and `CPWR` were deleted entirely** from both tables (2026-08-08). `NCC` is a ticker used by multiple unrelated companies across exchanges, producing a blended/nonsensical price series. `CPWR` showed price levels far outside the real company's historical range, root cause not fully pinned down. Judged not worth deeper forensics for two individually-minor names in a ~384-ticker universe.
- **Four rename/spin-off successor tickers are missing from `membership`**: `CPRI` (Michael Kors→Capri, 2018), `JEF` (Leucadia→Jefferies, 2018), `ANDV` (Tesoro→Andeavor, 2017), `ANTM` (WellPoint→Anthem, 2014). The predecessor tickers (`KORS`, `LUK`, `TSO`, `WLP`) now correctly show their real `End_Date` (fixed 2026-08-10), but adding the successor intervals would require researching exact historical S&P index-change dates for each — not done yet.
- **One uncorrected OHLC violation remains**: `UA` on 2021-05-05, `Open` a few cents below `Low`. Single row, judged immaterial to any factor/backtest.

## Bugs found and fixed (chronological, see research_log.md for full detail)

1. Membership reconstruction: unsorted dates (text vs. datetime), "Removed" events with no matching "Added" event — 2026-08-03
2. OHLCV loop ignored `membership.End_Date`, plus a loop-variable shadowing `datetime.date` — 2026-08-07
3. OHLC internal-consistency tolerance sign error (subtracting instead of adding, causing over-flagging) — 2026-08-07
4. `NCC` ticker collision, `CPWR` price-plateau corruption — 2026-08-08
5. `tickers.Date` stored as 2-digit-year strings across all 581,612 rows (systemic, but only chronology-affecting for `CCL`/`DIS`, the only two tickers with pre-2000 data); rename-gap `End_Date` values fixed — 2026-08-10

## Reproducing the database

1. `pip install -r requirements.txt`
2. `python main.py` (thin entry point that calls `build_database()` in `build_database.py` — the consolidated, already-corrected pipeline: table creation, membership reconstruction with the rename-date/exclusion fixes baked in, then OHLCV download)
3. Expect ~581,612 rows across 301 tickers on a clean run; some run-to-run variance in delisted-ticker failures is normal (`yfinance` data availability shifts over time)

`USProjectTester.ipynb` is the exploratory notebook this pipeline was originally debugged in — kept locally for reference but not the source of truth going forward; `build_database.py` is.
