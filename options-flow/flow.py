#!/usr/bin/env python3
"""
options_flow analyzer  -  free-data whale-positioning scanner.

Data source: yfinance (Yahoo). FREE, ~15-min delayed snapshots.
What it can REALLY see (free-data honest scope):
  * Volume vs Open Interest anomalies      -> fresh large positioning  (strong)
  * Notional-premium proxy (vol*price*100) -> "big money" prints        (proxy for sweeps)
  * Call/Put skew + IV per strike          -> directional bias & expected move
  * OI buildup over days                   -> via saved daily snapshots  (tracked from first run)

What it CANNOT see on free data: live tape, true sweep aggressor side, dark-pool prints.
Those need a paid feed (Unusual Whales / Polygon / etc.).

Noise filters applied:
  * same-day (0DTE) expiry skipped  (Yahoo zeroes its OI -> junk vol/OI)
  * deep-ITM, near-0% IV contracts excluded from directional reads (arb/assignment, not bets)

Usage:
    python flow.py MRVL
    python flow.py MU NVDA SNDK --min-premium 250000

Every ticker gets its own complete report, no flags needed: net flow verdict,
per-expiry $ flow (exact dates, exact call/put dollars, weeklies + monthlies
out ~18 months), fresh positioning, largest prints, OI buildup.
"""
import argparse
import os
import sys
from datetime import date

import pandas as pd
import yfinance as yf

SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
os.makedirs(SNAP_DIR, exist_ok=True)

DEEP_ITM = 0.06   # >6% in the money = "deep" (excluded from directional reads)
MIN_IV = 0.05     # <5% IV on a deep-ITM strike = arb/assignment junk, not a directional bet


def fnum(x, default=0.0):
    try:
        if x is None or pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def money(x):
    return f"${x:,.0f}"


def dte(expiry: str) -> int:
    """Days to expiry from today."""
    try:
        return (date.fromisoformat(expiry) - date.today()).days
    except ValueError:
        return -1


def pick_all_expiries(exps, cap=14, max_days=550):
    """The full picture in one pass: every weekly ≤45 DTE plus monthlies
    (3rd-Friday-ish) out to ~18 months — capped so we don't hammer Yahoo."""
    valid = [e for e in exps if 0 < dte(e) <= max_days]
    use = [e for e in valid
           if dte(e) <= 45 or 15 <= date.fromisoformat(e).day <= 21]
    if not use:
        use = valid[:3]
    return sorted(use)[:cap]


def load_chain(tk: yf.Ticker, use: list, spot: float):
    """Combined calls+puts across the given expiries."""
    if not use:
        return None, []
    frames = []
    for e in use:
        try:
            oc = tk.option_chain(e)
        except Exception:
            continue
        for side, df in (("C", oc.calls), ("P", oc.puts)):
            if df is None or df.empty:
                continue
            d = df.copy()
            d["side"] = side
            d["expiry"] = e
            frames.append(d)
    if not frames:
        return None, use
    out = pd.concat(frames, ignore_index=True)
    for col in ("volume", "openInterest", "lastPrice", "impliedVolatility", "strike", "bid", "ask"):
        if col not in out.columns:
            out[col] = 0.0
        out[col] = out[col].apply(fnum)

    out["volOI"] = out.apply(
        lambda r: (r["volume"] / r["openInterest"]) if r["openInterest"] > 0 else 0.0, axis=1
    )
    out["premium"] = out["volume"] * out["lastPrice"] * 100.0
    out["iv"] = out["impliedVolatility"]
    out["dte"] = out["expiry"].apply(dte)

    # moneyness: how far OTM(+) / ITM(-) as a fraction of spot, signed by side
    def itm_frac(r):
        if spot <= 0:
            return 0.0
        if r["side"] == "C":
            return (spot - r["strike"]) / spot          # >0 => ITM call
        return (r["strike"] - spot) / spot               # >0 => ITM put
    out["itm"] = out.apply(itm_frac, axis=1)             # positive = in the money
    # "directional" = not deep-ITM-with-dead-IV (those are arb/assignment, not bets)
    out["directional"] = ~((out["itm"] > DEEP_ITM) & (out["iv"] < MIN_IV))
    return out, use


def snapshot_and_diff(ticker: str, df: pd.DataFrame):
    today = date.today().isoformat()
    path = os.path.join(SNAP_DIR, f"{ticker}_{today}.csv")
    df[["side", "expiry", "strike", "openInterest", "volume"]].to_csv(path, index=False)
    priors = sorted(
        f for f in os.listdir(SNAP_DIR)
        if f.startswith(f"{ticker}_") and f.endswith(".csv") and today not in f
    )
    if not priors:
        return None, today
    prev_date = priors[-1].replace(f"{ticker}_", "").replace(".csv", "")
    try:
        prev = pd.read_csv(os.path.join(SNAP_DIR, priors[-1]))
    except Exception:
        return None, today
    merged = df[["side", "expiry", "strike", "openInterest"]].merge(
        prev[["side", "expiry", "strike", "openInterest"]],
        on=["side", "expiry", "strike"], how="left", suffixes=("", "_prev"))
    merged["oi_delta"] = merged["openInterest"] - merged["openInterest_prev"].fillna(0)
    builds = merged[merged["oi_delta"] > 0].sort_values("oi_delta", ascending=False)
    return (prev_date, builds), today


def verdict(dir_call, dir_put):
    if dir_put <= 0 and dir_call <= 0:
        return "NO CLEAR FLOW", 0
    if dir_put <= 0:
        return "BULLISH (calls only)", 99
    ratio = dir_call / dir_put
    if ratio >= 3:
        return "STRONGLY BULLISH", ratio
    if ratio >= 1.5:
        return "BULLISH", ratio
    if ratio <= 1 / 3:
        return "STRONGLY BEARISH", ratio
    if ratio <= 1 / 1.5:
        return "BEARISH", ratio
    return "MIXED / TWO-SIDED", ratio


VERDICT_EMOJI = {
    "STRONGLY BULLISH": "🟢🟢", "BULLISH": "🟢", "BULLISH (calls only)": "🟢🟢",
    "MIXED / TWO-SIDED": "🟡", "BEARISH": "🔴", "STRONGLY BEARISH": "🔴🔴",
    "NO CLEAR FLOW": "⚪",
}


def flow_bar(call_share, width=20):
    """Visual bar of call$ vs put$ split. call_share in 0..1."""
    fill = max(0, min(width, round(call_share * width)))
    return "🟩" * fill + "🟥" * (width - fill)


def build_report(ticker, max_expiries, min_premium, min_voloi, min_vol):
    """Run analysis and return a structured dict (no printing)."""
    tk = yf.Ticker(ticker)
    try:
        spot = fnum(tk.fast_info.get("last_price")) or fnum(tk.history(period="1d")["Close"].iloc[-1])
    except Exception:
        spot = 0.0

    exps_all = tk.options or ()
    use = pick_all_expiries(exps_all, cap=max_expiries)
    df, used = load_chain(tk, use, spot)
    R = {"ticker": ticker, "spot": spot, "expiries": used, "ok": df is not None and not df.empty,
         "thresholds": {"premium": min_premium, "voloi": min_voloi, "vol": min_vol}}
    if not R["ok"]:
        return R

    dirf = df[df["directional"]]

    # exact $ flow per expiry date
    rows = []
    for e in used:
        sub = dirf[dirf["expiry"] == e]
        if sub.empty:
            continue
        c = sub[sub["side"] == "C"]["premium"].sum()
        p = sub[sub["side"] == "P"]["premium"].sum()
        label, ratio = verdict(c, p)
        top = None
        if sub["premium"].max() > 0:
            t = sub.loc[sub["premium"].idxmax()]
            top = {"side": t["side"], "strike": t["strike"], "prem": t["premium"]}
        rows.append({"expiry": e, "dte": dte(e), "cprem": c, "pprem": p,
                     "ratio": ratio, "label": label,
                     "emoji": VERDICT_EMOJI.get(label, "⚪"),
                     "share": c / (c + p) if (c + p) else 0.5, "top": top})
    R["by_expiry"] = rows
    calls, puts = dirf[dirf["side"] == "C"], dirf[dirf["side"] == "P"]
    cvol, pvol = calls["volume"].sum(), puts["volume"].sum()
    cprem, pprem = calls["premium"].sum(), puts["premium"].sum()
    label, ratio = verdict(cprem, pprem)
    total = cprem + pprem

    R.update({
        "verdict": label, "ratio": ratio, "emoji": VERDICT_EMOJI.get(label, "⚪"),
        "cprem": cprem, "pprem": pprem,
        "call_share": (cprem / total) if total else 0.5,
        "cvol": cvol, "pvol": pvol,
        "pcr": (pvol / cvol) if cvol else float("inf"),
    })

    hot = dirf[(dirf["volOI"] >= min_voloi) & (dirf["volume"] >= min_vol)].sort_values("volOI", ascending=False).head(10)
    R["hot"] = hot.to_dict("records")

    big = dirf[dirf["premium"] >= min_premium].sort_values("premium", ascending=False).head(10)
    R["big"] = big.to_dict("records")

    if spot > 0:
        # IV read on nearest 3 expiries only (LEAP IV would dilute the ATM number)
        dfn = df[df["expiry"].isin(used[:3])].copy()
        dfn["dist"] = (dfn["strike"] - spot).abs()
        ncalls, nputs = dfn[dfn["side"] == "C"], dfn[dfn["side"] == "P"]
        oc = ncalls[ncalls["strike"] > spot]["iv"]
        op = nputs[nputs["strike"] < spot]["iv"]
        cic = oc.mean() * 100 if not oc.empty else 0
        cip = op.mean() * 100 if not op.empty else 0
        R["iv"] = {"atm": dfn.nsmallest(6, "dist")["iv"].mean() * 100, "otm_call": cic, "otm_put": cip,
                   "skew": "put skew (downside hedging)" if cip > cic + 2
                   else "call skew (upside chase)" if cic > cip + 2 else "balanced"}

    diff, today = snapshot_and_diff(ticker, df)
    R["oi"] = {"snapshot": f"{ticker}_{today}.csv",
               "prev_date": diff[0] if diff else None,
               "builds": diff[1].head(8).to_dict("records") if diff else []}
    return R


def mny_tag(itm):
    return "ITM" if itm > 0.01 else ("OTM" if itm < -0.01 else "ATM")


def side_md(side):
    return "📞 CALL" if side == "C" else "📕 PUT"


def render_md(R):
    """GitHub-flavored Markdown for in-chat display."""
    L = []
    if not R["ok"]:
        return f"### ⚠️ {R['ticker']} — no options data available\n"
    e = R["expiries"]
    exps = f"{e[0]} → {e[-1]} ({len(e)} dates)" if e else "none"
    L.append(f"## 📊 {R['ticker']} — Options Flow Scan")
    L.append(f"**Spot ~${R['spot']:,.2f}** · expiries {exps} · _0DTE skipped · free data (~15m delayed)_\n")

    share = R["call_share"]
    rtxt = f" ({R['ratio']:.1f}× call $ / put $)" if 0 < R["ratio"] < 90 else ""
    L.append(f"### {R['emoji']} NET DIRECTIONAL FLOW: **{R['verdict']}**{rtxt}")
    L.append(f"`{flow_bar(share)}` **{share*100:.0f}% calls**")
    L.append(f"> Directional call $ **{money(R['cprem'])}**  vs  put $ **{money(R['pprem'])}**\n")

    pcr_read = ("bullish" if R["pcr"] < 0.7 else "bearish" if R["pcr"] > 1.3 else "neutral")
    L.append("| Quick read | Value |")
    L.append("|---|---|")
    L.append(f"| Put/Call by **count** | {R['pcr']:.2f} → {pcr_read} on contracts |")
    L.append(f"| Put/Call by **dollars** | {R['ratio']:.1f}× → bigger {'call' if share>=0.5 else 'put'} bets |")
    if "iv" in R:
        iv = R["iv"]
        L.append(f"| IV (ATM / OTM call / OTM put) | {iv['atm']:.0f}% / {iv['otm_call']:.0f}% / {iv['otm_put']:.0f}% → {iv['skew']} |")
    L.append("")

    L.append("### 📅 Flow by Expiry — exact dates, exact dollars")
    L.append(expiry_flow_table(R))
    L.append("")

    L.append("### 🔥 Fresh Positioning — Volume > Open Interest")
    if R["hot"]:
        L.append("| Exp | Side | Strike | Vol | OI | Vol/OI | Premium | IV |")
        L.append("|---|:---:|--:|--:|--:|--:|--:|--:|")
        for r in R["hot"]:
            L.append(f"| {r['expiry']} | {side_md(r['side'])} | {r['strike']:,.1f} | {r['volume']:,.0f} | "
                     f"{r['openInterest']:,.0f} | {r['volOI']:.1f}× | {money(r['premium'])} | {r['iv']*100:.0f}% |")
    else:
        L.append("_(none above thresholds)_")
    L.append("")

    L.append(f"### 💰 Largest $ Prints (≥ {money(R['thresholds']['premium'])})")
    if R["big"]:
        L.append("| Exp | Side | Strike | Vol | Premium | Moneyness | IV |")
        L.append("|---|:---:|--:|--:|--:|:--:|--:|")
        for r in R["big"]:
            L.append(f"| {r['expiry']} | {side_md(r['side'])} | {r['strike']:,.1f} | {r['volume']:,.0f} | "
                     f"{money(r['premium'])} | {mny_tag(r['itm'])} | {r['iv']*100:.0f}% |")
    else:
        L.append("_(none above threshold)_")
    L.append("")

    L.append("### 📈 Open-Interest Buildup")
    oi = R["oi"]
    if oi["prev_date"] is None:
        L.append(f"_Baseline snapshot saved (`{oi['snapshot']}`). Run again on a later day to see multi-day buildup._")
    elif not oi["builds"]:
        L.append(f"_vs {oi['prev_date']}: no net OI increase._")
    else:
        L.append(f"Top OI increases vs **{oi['prev_date']}**:\n")
        L.append("| Exp | Side | Strike | +OI |")
        L.append("|---|:---:|--:|--:|")
        for r in oi["builds"]:
            L.append(f"| {r['expiry']} | {side_md(r['side'])} | {r['strike']:,.1f} | +{r['oi_delta']:,.0f} |")
    L.append("")
    return "\n".join(L)


def money_short(x):
    return f"${x/1e6:.2f}M" if x >= 1e6 else f"${x/1e3:.0f}K"


def expiry_flow_table(R, fenced=True):
    """The core view: exact $ call/put flow per exact expiry date."""
    rows = R["by_expiry"]
    if not rows:
        return "_(no directional flow found)_"
    barw = 16
    L = [f"{'DATE':<12}{'DTE':>4}  {'CALL $':>12}  {'PUT $':>12}  {'CALLS ' + '─'*(barw-6) + ' PUTS':<{barw+6}} NET     TOP PRINT"]
    for r in rows:
        fill = max(0, min(barw, round(r["share"] * barw)))
        bar = "█" * fill + "░" * (barw - fill)
        net = f"{r['ratio']:.1f}×" if 0 < r["ratio"] < 90 else "∞"
        t = r["top"]
        top = f"{t['side']} ${t['strike']:g} {money_short(t['prem'])}" if t else "—"
        L.append(f"{r['expiry']:<12}{r['dte']:>4}  {money(r['cprem']):>12}  {money(r['pprem']):>12}  "
                 f"{bar} {r['share']*100:>3.0f}%  {net:>5}   {top}")
    tot_c = sum(r["cprem"] for r in rows)
    tot_p = sum(r["pprem"] for r in rows)
    L.append(f"{'TOTAL':<12}{'':>4}  {money(tot_c):>12}  {money(tot_p):>12}")
    body = "\n".join(L)
    return f"```\n{body}\n```" if fenced else body


def render_text(R):
    """Plain aligned console output."""
    out = ["=" * 74]
    if not R["ok"]:
        return f"  {R['ticker']}: no options data available."
    e = R["expiries"]
    out.append(f" {R['ticker']}   spot ~${R['spot']:,.2f}   expiries "
               f"{f'{e[0]} -> {e[-1]} ({len(e)} dates)' if e else 'none'}  (0DTE skipped)")
    out.append("=" * 74)
    rtxt = f"   (call $/put $ = {R['ratio']:.1f}x)" if 0 < R["ratio"] < 90 else ""
    out.append(f"\n>>> NET DIRECTIONAL FLOW: {R['verdict']}{rtxt}")
    out.append(f"    {flow_bar(R['call_share'], 20).encode('ascii','replace').decode()}  {R['call_share']*100:.0f}% calls")
    out.append(f"    directional call $ {money(R['cprem'])}  vs  put $ {money(R['pprem'])}")
    out.append(f"\n[1] CALL/PUT  vol {R['cvol']:,.0f}C / {R['pvol']:,.0f}P  -> P/C {R['pcr']:.2f}")
    if "iv" in R:
        iv = R["iv"]
        out.append(f"[2] IV  ATM ~{iv['atm']:.0f}% | OTMc ~{iv['otm_call']:.0f}% OTMp ~{iv['otm_put']:.0f}%  -> {iv['skew']}")
    out.append("\n[3] FLOW BY EXPIRY")
    out.append(expiry_flow_table(R, fenced=False))
    out.append("\n[4] VOLUME >> OI")
    for r in R["hot"]:
        out.append(f"    {r['expiry']:<11}{r['side']:<3}{r['strike']:>9.1f}  vol {r['volume']:>8,.0f}"
                   f"  vol/OI {r['volOI']:>5.1f}  {money(r['premium'])}")
    out.append("\n[5] LARGEST $ PRINTS")
    for r in R["big"]:
        out.append(f"    {r['expiry']:<11}{r['side']:<3}{r['strike']:>9.1f}  {money(r['premium']):>14}"
                   f"  {mny_tag(r['itm'])}")
    oi = R["oi"]
    out.append(f"\n[6] OI BUILDUP  (snapshot {oi['snapshot']})")
    if oi["prev_date"] is None:
        out.append("    baseline saved - run again later for buildup")
    else:
        for r in oi["builds"]:
            out.append(f"    {r['expiry']:<11}{r['side']:<3}{r['strike']:>9.1f}  +OI {r['oi_delta']:>9,.0f}")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Free-data options-flow / whale-positioning scanner")
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--expiries", type=int, default=14,
                    help="max expiry dates to pull (weeklies ≤45 DTE + monthlies out ~18mo)")
    ap.add_argument("--min-premium", type=float, default=250_000)
    ap.add_argument("--min-voloi", type=float, default=2.0)
    ap.add_argument("--min-vol", type=int, default=300)
    ap.add_argument("--format", choices=["md", "text"], default="md",
                    help="md = chat Markdown UI (default), text = plain console")
    args = ap.parse_args()
    # Windows consoles default to cp1252 and choke on emoji/box chars — force UTF-8
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    render = render_md if args.format == "md" else render_text
    blocks = [render(build_report(t.upper(), args.expiries, args.min_premium,
                                  args.min_voloi, args.min_vol))
              for t in args.tickers]
    sep = "\n\n---\n\n" if args.format == "md" else "\n\n"
    print(sep.join(blocks))


if __name__ == "__main__":
    main()
