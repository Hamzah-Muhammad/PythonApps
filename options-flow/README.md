# Options Flow Scanner

A free-data **options-flow / whale-positioning scanner**. Given one or more tickers, it reads the options chain and surfaces where the *dollars* are positioned — call vs. put premium, fresh large positioning, implied-volatility skew, and multi-day open-interest buildup.

Built to answer one question quickly: *are big players leaning bullish or bearish on this name right now?*

## Features

- **Net directional flow** — directional call $ vs. put $, with a verdict (Strongly Bullish → Strongly Bearish) and a visual bar.
- **Fresh positioning** — strikes where **Volume > Open Interest** (new bets being opened, not old ones).
- **Largest $ prints** — biggest notional-premium contracts (a proxy for "big money" sweeps).
- **IV skew** — ATM vs. OTM call/put implied vol → expected move and hedging vs. chasing bias.
- **OI buildup** — saves a daily snapshot and diffs against prior days to track open-interest growth.
- Two output modes: GitHub-flavored **Markdown** (default) or plain **console text**.

## Install

```bash
pip install yfinance pandas
```

## Usage

```bash
# single ticker
python flow.py MU

# multiple tickers with options
python flow.py MU NVDA SNDK --expiries 4 --min-premium 250000

# plain console output instead of Markdown
python flow.py AAPL --format text
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `tickers` | — | One or more ticker symbols (positional). |
| `--expiries` | `3` | How many nearest expirations to include. |
| `--min-premium` | `250000` | Minimum $ premium to list a contract in "Largest $ Prints". |
| `--min-voloi` | `2.0` | Minimum Volume/Open-Interest ratio for "Fresh Positioning". |
| `--min-vol` | `300` | Minimum contract volume for "Fresh Positioning". |
| `--format` | `md` | `md` for Markdown, `text` for console. |

## How to read it

**Follow the dollars, not the contract count.** A divergence — more put *contracts* but more call *dollars* — usually means retail hedging with cheap puts while larger, directional money buys calls. The "Net Directional Flow" verdict is dollar-weighted for this reason.

## Honest limitations (free data)

This uses [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo) — free, but **~15-minute delayed snapshots**. It therefore **cannot** see:

- Live tape or the true **sweep aggressor side** (buy vs. sell).
- Dark-pool prints.

Those require a paid feed (Unusual Whales, Polygon, etc.). Premium is a `volume × lastPrice × 100` proxy, not confirmed executions.

Noise filters applied automatically:
- Same-day (0DTE) expiries are skipped (Yahoo zeroes their OI → junk Vol/OI).
- Deep-ITM, near-0% IV contracts are excluded from directional reads (those are arbitrage/assignment, not directional bets).

OI buildup only works from your **first run onward** — it builds history from the snapshots it saves locally (`snapshots/`, gitignored).

## Dependencies

- `yfinance`
- `pandas`
- Python 3.10+
