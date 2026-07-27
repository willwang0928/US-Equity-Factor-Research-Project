# US Equity Factor Research Project

An independently-built quantitative research pipeline that constructs original equity factors for the US stock market, tests whether they predict returns, combines them into a composite signal, and validates that signal out-of-sample.

**Core research question:** Do a small set of original, economically-motivated factors (momentum, value, volatility) show real, out-of-sample predictive power on US equity returns — and does combining them produce a stronger signal than any one alone?

This project mirrors the core research loop (build factor → check IC → combine → verify) end-to-end in plain Python/pandas, without relying on a platform's built-in backtesting engine.

## Plan

**Phase 1 — Data Infrastructure**
Clean OHLCV data pipeline for a US equity universe (starting with S&P 500), stored in SQLite. Uses *historical* index constituents (not just today's list) to avoid survivorship bias.

**Phase 2 — First Factor & Backtest Mechanics**
Momentum factor. Self-implemented backtest loop: rank stocks → decile buckets → forward returns → IC/Sharpe.

**Phase 3 — Multi-Factor Composite**
Add value (book-to-price) and volatility factors. Combine into a composite score. Realistic transaction costs and slippage from this point forward. A reserved, untouched time period becomes the out-of-sample test set.

**Phase 4 — Risk Layer**
Position sizing, drawdown limits, and beta-neutralization of the signal (self-implemented).

**Phase 5 — Out-of-Sample Validation**
Run the finished strategy on the reserved period. Report the result honestly, whatever it is.

**Phase 6 — Optional Stretch: ML Layer**
Regression / gradient-boosted model combining the factors, using time-ordered cross-validation (never shuffled folds).

## Principles

- No frictionless backtests — transaction costs and slippage are modeled from Phase 3 onward
- No survivorship bias — historical index membership, including delisted/bankrupt names
- A genuine out-of-sample test set, reserved from the start and never tuned on
- Honest reporting of results, strong or weak
- A running research log (`docs/research_log.md`) documenting hypotheses, what worked, what didn't, and why each design decision was made

## Status

Phase 1 in progress.
