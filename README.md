# PythonApps

A collection of standalone Python tools ("mini apps") — each solves one specific goal and lives in its own folder with its own README, usage examples, and dependencies.

## Projects

| Project | What it does |
|--------|--------------|
| [MeridianCalc](./MeridianCalc) | A long-form math calculator with textbook display: stacked fractions, powers and roots, exact answers, a cursor dial, live results and history. |
| [options-flow](./options-flow) | Free-data options-flow / "whale positioning" scanner — reads call/put dollar flow, fresh volume-vs-open-interest positioning, IV skew, and multi-day OI buildup for any ticker. |

_More tools will be added over time._

*Windows shell-script equivalents live in the [ShellScriptApps](https://github.com/Hamzah-Muhammad/ShellScriptApps) repo.*

## Getting started

Each tool is self-contained. To run one, open its folder and follow its README. General setup:

```bash
# clone the repo
git clone https://github.com/Hamzah-Muhammad/PythonApps.git
cd PythonApps

# (recommended) create a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
# source .venv/bin/activate   # macOS/Linux

# install a script's dependencies (see its README), e.g.
pip install yfinance pandas
```

## Requirements

- Python 3.10+ (developed on 3.13)
- Per-script dependencies are listed in each tool's README.

## License

MIT — see individual scripts for any data-source attribution.

## Author

[Hamzah Muhammad](https://github.com/Hamzah-Muhammad)
