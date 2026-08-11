# Research Log

Running log of hypotheses, what was tried, what worked, what didn't (including negative results), and why each design decision was made.

## Template

### YYYY-MM-DD — Title

**Hypothesis:**

**What was tried:**

**Result:**

**Why (design rationale):**

## Entries

### 2026-08-03 — Membership reconstruction algorithm

**Hypothesis:** To build a survivorship-bias-free universe, historical S&P 500 membership needs to be reconstructed from add/remove events over time, not taken from today's constituent list.

**What was tried:** Loaded Wikipedia's table of S&P 500 index changes (Added/Removed tickers + dates). Wrote a loop walking through events in chronological order, tracking currently-active constituents and recording completed membership intervals as they closed.

**Result:** Hit two bugs: (1) dates were stored as plain text, so sorting wasn't actually chronological — fixed with `pd.to_datetime`; (2) some "Removed" events referenced tickers that were never recorded as "Added" (Wikipedia's pre-1976 data is incomplete), causing a crash — fixed by skipping with a logged note instead of crashing. Final version also captures still-active tickers (never removed) with `None` as end date. Produced 384 reconstructed membership intervals.

**Why (design rationale):** Using only today's S&P 500 list would hide every company that was removed (bankruptcy, M&A, delisting), making backtests look artificially strong (survivorship bias). Reconstructing real membership windows lets later factor analysis restrict to companies actually eligible on any given historical date.

### 2026-08-06 — Membership persisted to DB + OHLCV pipeline

**Hypothesis:** Reconstructed data needs to live in the actual SQLite database (not notebook memory) to persist across sessions; a price pipeline needs to be proven on one ticker before scaling to hundreds.

**What was tried:** Cleared fake test rows from `membership`, converted `Timestamp` objects to date strings, inserted all 384 records. Built a `yfinance`-based OHLCV pipeline, proved it end-to-end on AAPL, then scaled it into a loop over all 384 historical tickers, using each ticker's own `membership.Start_Date` as the download start and `auto_adjust=True` to avoid split/dividend price distortion.

**Result:** 384 membership records persisted. The OHLCV loop needed several rounds of debugging (Timestamp-binding errors, a missing `continue` that caused some failed tickers to be double-counted) before a clean run: 651,843 rows inserted for 307/384 tickers; 77 failed with no data available, almost entirely due to real M&A/bankruptcy/delisting (e.g. `ABK`, `ALXN`, `CERN`, `ATVI`, `TWTR`, `SIVB`, `FRC`).

**Why (design rationale):** Downloading from each ticker's actual index-join date (rather than a fixed date) preserves real history instead of an arbitrarily truncated window. `auto_adjust=True` ensures price series reflect true investor returns, not split/dividend artifacts. Missing tickers are logged as an honest, documented limitation rather than silently dropped.

### 2026-08-07 — Data quality spot-check uncovered two pipeline bugs

**Hypothesis:** Before building factors on top of the 651,843-row `tickers` table, it needs a basic quality pass — duplicates, nulls, zero/negative prices and volume — to catch pipeline errors before they silently corrupt downstream calculations.

**What was tried:** Ran a sequence of SQL checks against `tickers`: duplicate `(Ticker, Date)` pairs (structurally impossible — that pair is the table's composite primary key), null OHLCV values (none found), and zero/negative price or volume (`WHERE Volume <= 0`). The volume check surfaced two tickers, `CPWR` and `CVG`, with thousands of zero-volume rows each — far beyond an isolated no-trade day. Digging into `CPWR` specifically: `membership.End_Date` correctly showed 2011-12-31 (when it left the S&P 500 index), but the `tickers` table had rows for `CPWR` all the way out to 2026-07-31, with real (nonzero-volume) trades mixed in as late as 2026-08-05 — over a decade past when the real Compuware stopped existing as a public company.

Traced this to the OHLCV download loop (in `USProjectTester.ipynb`): (1) it called `yf.download(ticker, start=start_date, end=date.today(), ...)` for every ticker, never referencing `membership.End_Date` at all, so delisted tickers kept requesting/receiving years of data past when they should have stopped; and (2) an earlier, unrelated cell used `date` as a `for`-loop variable name (`for ticker, date, open_price, ... in real_tickers[...]`), which shadowed the `datetime.date` class imported at the top of the notebook — so once that cell had been run in the session, `date.today()` in the download loop crashed with `'str' object has no attribute 'today'` for every currently-active ticker (`End_Date is None`), silently failing 325 tickers on the first fix attempt.

**Result:** Fixed both: `query1` now selects `End_Date` alongside `Ticker`/`Start_Date`; the download loop computes `end = end_date if end_date else date.today()` and passes that to `yf.download`; the shadowing loop variable was renamed to `tick_date`. Cleared `tickers`, restarted the kernel (to guarantee no other stale/shadowed state survived), and re-ran the full pipeline: 581,612 rows for 300/384 tickers, 84 failures (up from 77 — expected, since a few tickers previously received phantom post-delisting data instead of correctly failing/truncating). `CPWR` now correctly maxes out at 2011-12-30. Noted but not yet fixed: a handful of tickers (`JOYG`, `KORS`, `LUK`, `TSO`, `WLP`) still show `End_Date IS NULL` in `membership` despite being real historical renames/acquisitions (Joy Global, Michael Kors→Capri, Leucadia→Jefferies, Tesoro→Andeavor, WellPoint→Anthem) — likely gaps in the Wikipedia-sourced add/remove event table from the 2026-08-03 membership reconstruction, where a ticker rename wasn't captured as a clean "Removed" event.

**Why (design rationale):** A pipeline that silently downloads data past a security's real lifetime produces exactly the kind of quiet, plausible-looking corruption that's hardest to catch later (flat prices, occasional real-looking volume) — it wouldn't have thrown an error, just poisoned any factor or backtest touching those tickers. Bounding every download by the ticker's actual `membership` window, and fixing the variable-shadowing bug outright (rather than just re-running cells in the right order) closes off a class of bug that would otherwise resurface unpredictably.

**Follow-up — OHLC internal-consistency check:** Also checked for logically impossible rows (`High < Low`, or `Open`/`Close` falling outside `[Low, High]`). A naive strict-inequality check flagged ~250 rows, but nearly all were floating-point noise from the `auto_adjust` recalculation (differences on the order of 1e-13 — e.g. `Close` a few units in the 15th decimal place below `Low`). Rewrote the check with a $0.01 tolerance; first attempt still over-flagged because the tolerance was subtracted (`Open > High - 0.01`) instead of added (`Open > High + 0.01`) on the two "shouldn't exceed High" conditions — `High - 0.01` makes the threshold looser, not stricter, so it matched the extremely common case of `Open`/`Close` landing exactly at `High`. After fixing the sign, only 2 genuine violations remain out of 581,612 rows: `NCC` (2013-11-15) and `UA` (2021-05-05), both with `Open` a few cents below `Low`. Decision: leave both rows in place rather than editing or dropping them — the sample is too small to matter for any factor/backtest, and there's no reliable way to know the "correct" value to substitute. Revisit only if either ticker surfaces as an outlier in an actual factor calculation later.

Still open: the `End_Date IS NULL` rename gaps (`JOYG`, `KORS`, `LUK`, `TSO`, `WLP`) in `membership` — carried forward rather than declared "done" prematurely.

### 2026-08-08 — Single-day extreme-price-jump check surfaced two more bad tickers

**Hypothesis:** Beyond internal OHLC consistency, `tickers` should be checked for implausible single-day price moves — a day-over-day `Close` change beyond some threshold (started at ±20%) — since these can indicate either genuine volatility or further pipeline/data-source corruption, similar to what the zero-volume and OHLC checks had already caught.

**What was tried:** Used `LAG(Close, 1) OVER (PARTITION BY Ticker ORDER BY Date)` to pull each row's previous trading day's `Close` alongside the current one, wrapped as a subquery, then filtered for `|percent change| > 20%`. The initial run returned a long list dominated by explainable volatility (COVID-crash-week moves in `AAL`, `DAL`, `CCL`, etc.), but two tickers stood out for the wrong reasons:

- `NCC`: hundreds of rows alternating between two price levels roughly every Friday, for six-plus years straight — not plausible market behavior. Looked up the ticker and confirmed `NCC` is used by multiple, unrelated companies across exchanges; `yfinance` had evidently returned a blended/mismatched series under that one symbol.
- `CPWR`: prices forming a "staircase" (same value repeated for many consecutive days, consistent with thin trading), but reaching implausible levels for the real company (Compuware) — e.g. ~$230/share in December 2006, versus its actual $5-$20 range through most of 2007-2011. Confirmed via `membership` that `CPWR` only has one clean interval (1998-12-11 to 2011-12-31), ruling out a multiple-download/adjustment-mismatch theory. Root cause not fully pinned down, but the price levels are clearly wrong.

**Result:** Deleted `NCC` and `CPWR` from both `tickers` and `membership` (kept both tables consistent, since a `membership` row with no matching `tickers` data would create silent null-price rows in any later join). Re-ran the jump check at a stricter ±100% threshold to separate remaining noise from real problems — the only survivor was `UA` on `2021-05-05`, which is the already-known, already-accepted OHLC violation from the 2026-08-07 check (not a new issue). Re-running the ±100% check after the deletions returned an empty list.

**Why (design rationale):** A handful of corrupted tickers with wild but "in-range-looking" price swings are worse than obviously-missing data, because they'd silently distort any factor or backtest touching them (e.g. momentum or volatility factors would treat `NCC`'s weekly bounce as real signal). Given the project's ~384-ticker universe and the goal of being representative rather than exhaustive, decided against deeper root-cause forensics on two individually-minor small/micro-cap names — deleting them outright was judged the better time/rigor tradeoff, documented here as an explicit, honest exclusion rather than a silent one.

Still open: the `End_Date IS NULL` rename gaps (`JOYG`, `KORS`, `LUK`, `TSO`, `WLP`) in `membership` — carried forward rather than declared "done" prematurely.

### 2026-08-10 — Date-format bug in `tickers.Date` and closing the rename gaps

**Hypothesis:** Before writing a final Phase 1 data-layer summary, the dataset needs one more honest look — is anything else structurally wrong that the earlier checks (nulls, zero-volume, OHLC consistency, price jumps) wouldn't have caught? And can the still-open rename-gap tickers finally be closed out?

**What was tried:** Ran `MIN(Date)`/`MAX(Date)` on `tickers` as a sanity check before summarizing and got back `'00-01-03'` / `'99-12-31'` — not real dates. `SELECT DISTINCT LENGTH(Date)` showed every single row (all 581,612) stored as an 8-character `YY-MM-DD` string instead of the intended 10-character `YYYY-MM-DD` — a bug in the OHLCV insert step (likely a `strftime` format slip), separate from `membership.Start_Date`/`End_Date`, which were already correct 4-digit-year strings. Checked actual impact: only two tickers, `CCL` (data from 1998) and `DIS` (data from 1976), have any pre-2000 rows, so only those two could have had chronology scrambled by 2-digit lexical sort (`'00-...'` sorting before `'99-...'`) in the prior OHLC-consistency and price-jump `ORDER BY Date` checks.

Fixed with a single `UPDATE`: prefix each `Date` with `'20'` if the 2-digit year is ≤26, else `'19'` — safe because the dataset's true range (1976–2026, per `membership.Start_Date`) has no gap that would make the pivot ambiguous. Re-ran the OHLC-consistency and >20% price-jump checks scoped to just `CCL`/`DIS` post-fix: zero OHLC violations, 9 jumps all attributable to real market history (Black Monday 1987 for `DIS`; post-9/11 reopening and COVID crash/recovery for `CCL`) — confirms the earlier checks weren't hiding anything for these two.

Separately, closed the `JOYG`/`KORS`/`LUK`/`TSO`/`WLP` rename gaps flagged on 2026-08-07. First discovered these five have **zero rows** in `tickers` (the OHLCV pipeline's `yf.download` silently failed on all of them — old/retired ticker symbols yfinance no longer resolves), so unlike `CPWR` they weren't polluting data, just sitting there with `End_Date IS NULL` implying (wrongly) that they're still active constituents. Set `End_Date` to each company's real rename/acquisition date: `JOYG` 2017-04-28 (Komatsu acquisition), `KORS` 2018-12-03 (renamed Capri Holdings/`CPRI`), `LUK` 2018-03-01 (renamed Jefferies Financial Group/`JEF`), `TSO` 2017-08-01 (renamed Andeavor/`ANDV`), `WLP` 2014-12-03 (renamed Anthem/`ANTM`). Checked whether the successor tickers (`CPRI`, `JEF`, `ANDV`, `ANTM`) already exist in `membership` under their new symbols — they don't (only `MPC` exists, an unrelated pre-existing 2011 entry) — so those four successor intervals remain a known, undone gap in the reconstructed membership history, not silently papered over.

**Result:** `tickers.Date` is now uniformly `YYYY-MM-DD` across all 581,612 rows (`MIN`/`MAX` now read `1976-07-01` / `2026-08-06`, matching `DIS`'s and the latest download date). All five rename-gap tickers now have correct `End_Date` values in `membership`. `CCL`/`DIS` re-checks came back clean.

**Why (design rationale):** A silently-wrong date format is worse than a crash — every prior query that touched `tickers.Date` ran without error and mostly returned correct-looking results, because the bug only bites at a century boundary. Catching it now, before Phase 2 factor code starts doing date arithmetic and rolling windows across `tickers`, avoids baking a hard-to-detect off-by-century bug into every downstream calculation. For the rename gaps: correcting `End_Date` on the five old tickers closes the "silently still active" mischaracterization, but adding the four successor-ticker membership intervals would require researching real historical S&P 500 index-change dates for each — out of scope for this pass, so it's logged as an explicit, bounded limitation (consistent with how `NCC`/`CPWR` and the 77-84 failed-download tickers were handled) rather than either faking dates or quietly leaving the mischaracterization in place.

Phase 1 data layer is now considered complete, documented in `docs/data_layer.md`. Known, explicitly-accepted limitations carried into Phase 2: `NCC`/`CPWR` excluded entirely; ~84 tickers with no price data due to real M&A/bankruptcy/delisting; successor tickers for the five 2026-08-10 renames (`CPRI`, `JEF`, `ANDV`, `ANTM`) not yet added to `membership`; two uncorrected OHLC violations (`NCC`-era finding superseded by deletion; `UA` 2021-05-05 remains, single-row, immaterial).
