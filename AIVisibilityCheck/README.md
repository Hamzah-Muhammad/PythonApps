# AIVisibilityCheck

A small command line tool that checks how visible a website (default: minniai.com) is in search engines and AI assistants, and writes a dated scoreboard. Run it every week and compare the numbers.

## What it measures

1. **Classic search** (no API): for each query in `queries.yaml`, it fetches Bing and DuckDuckGo result pages and records the first position (top 20) where a `minniai.com` URL shows up, or `none`. It waits 3 seconds between requests. If a CAPTCHA or bot-check page comes back, it stops that engine and says so in the scoreboard.
   - Bing sometimes serves unrelated "decoy" results to scripts. The tool checks that results match the query words, retries with two URL variants, and marks the cell `unreliable` instead of reporting a false `none`.
   - Google is not scraped. If you set `GSC_CREDENTIALS` it reads Google Search Console instead (see below).
   - Brave Search blocks bots, so it is skipped.
2. **AI assistants** (needs API keys, each one optional): for each *intent* query it asks OpenAI (Responses API with `web_search`), Perplexity (`sonar`) and Anthropic (Messages API with the `web_search` server tool). Per answer it records whether a product name or minniai.com appears in the text (`mentioned`), whether a minniai.com URL is cited (`cited`), which domains are cited, and which competitor domains (from `queries.yaml`) are cited.

## Setup

```
cd "C:\Apps\Python&ShellApps\PythonApps\AIVisibilityCheck"
pip install -r requirements.txt
```

Environment variables (all optional; a missing one skips that column and says so):

| Variable | Used for |
|---|---|
| `OPENAI_API_KEY` | OpenAI assistant column. Model via `OPENAI_MODEL` (default `gpt-4.1-mini`) |
| `PERPLEXITY_API_KEY` | Perplexity column. Model via `PERPLEXITY_MODEL` (default `sonar`) |
| `ANTHROPIC_API_KEY` | Anthropic column. Model via `ANTHROPIC_MODEL` (default `claude-haiku-5-5`), search tool via `ANTHROPIC_WEB_SEARCH_TOOL` (default `web_search_20250305`) |
| `GSC_CREDENTIALS` | Path to a Search Console service-account JSON. Needs `pip install google-auth`. The service account must be added as a user on the property. `GSC_SITE` sets the property (default `sc-domain:minniai.com`) |

No keys are stored in any file.

## Run

```
python aivisibility.py --dry-run          # print every call, no network
python aivisibility.py --only search      # Bing + DuckDuckGo (+ Search Console if set)
python aivisibility.py --only assistants  # AI assistants
python aivisibility.py                    # everything
python aivisibility.py --queries other.yaml
```

Output goes to `results/`:

- `YYYY-MM-DD.json`: raw data (answers, cited URLs). Ignored by git.
- `scoreboard.md`: tables of query x source. Search cells are a position or `none`; assistant cells are `cited`, `mentioned` or `absent`. Also printed to the screen.
- `history.csv`: one row per run per query per source, so you can diff or chart weeks. Running twice on the same day replaces that day's rows for the sources that ran.

## Weekly with Windows Task Scheduler

`run_weekly.ps1` runs the tool and saves a log. Create the task once (adjust the day and time):

```
schtasks /Create /TN "AIVisibilityCheck" /SC WEEKLY /D MON /ST 09:00 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\Apps\Python&ShellApps\PythonApps\AIVisibilityCheck\run_weekly.ps1\""
```

Set the API keys as *user* environment variables so the task can see them. Remove it with `schtasks /Delete /TN "AIVisibilityCheck"`.

## Cost

Search is free. Assistants: one call per query per provider (6 queries x 3 providers = 18 calls), `max_tokens` about 600. The tool prints an estimate from the usage fields and list prices hard-coded at the top of the script (check them, they change). Expect roughly 10 to 30 US cents per full run, mostly the per-search fees.

## What it does NOT measure

- Google results (only through Search Console, which shows your own impressions, not rank for any query you choose).
- Brave, Yandex, Kagi, or any other engine.
- ChatGPT, Claude.ai, Gemini or Copilot as consumers use them. API answers with web search are a proxy; they can differ from the apps.
- Personalised or location-specific results. Results move between runs, so look at trends, not single cells.
- Whether being cited leads to clicks or installs.

## Side effects and disclaimer

Makes outbound web requests to Bing, DuckDuckGo and the AI providers you give keys for, and writes files under `results/`. Nothing else on your machine is changed. Scraping search result pages may break the terms of those sites and the HTML can change without notice; use it at low volume, as designed, and at your own risk. API calls cost real money on your accounts.
