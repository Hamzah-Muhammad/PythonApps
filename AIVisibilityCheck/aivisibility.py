#!/usr/bin/env python3
"""AIVisibilityCheck: a dated scoreboard of how visible a site is in search
engines and AI assistants. See README.md. Keys come from environment variables
only; nothing secret is written to disk."""
import argparse
import base64
import csv
import datetime as dt
import json
import os
import re
import sys
import time
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests
import yaml

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
SEARCH_DELAY = 3.0   # seconds between search-engine requests
TOP_N = 20
MAX_TOKENS = 600

# Prices in USD, used only for the printed estimate. Check the providers' pricing pages.
PRICES = {
    "openai": {"in": 0.40e-6, "out": 1.60e-6, "per_search": 0.025},       # gpt-4.1-mini + web search
    "perplexity": {"in": 1.0e-6, "out": 1.0e-6, "per_search": 0.005},     # sonar, low context
    "anthropic": {"in": 0.10e-6, "out": 0.50e-6, "per_search": 0.010},    # haiku 5.5 + web search
}
MODELS = {
    "openai": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
    "perplexity": os.environ.get("PERPLEXITY_MODEL", "sonar"),
    "anthropic": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5"),
}
KEYS = {"openai": "OPENAI_API_KEY", "perplexity": "PERPLEXITY_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
ENGINES = ["bing", "duckduckgo"]


class Captcha(Exception):
    pass


# ---------------------------------------------------------------- helpers
def host_of(url):
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def is_ours(url, domain):
    h = host_of(url)
    return h == domain or h.endswith("." + domain)


def load_cfg(path):
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg.setdefault("domain", "minniai.com")
    cfg.setdefault("product_terms", [cfg["domain"]])
    cfg.setdefault("competitors", [])
    cfg["intent"] = cfg.get("intent") or []
    cfg["brand"] = cfg.get("brand") or []
    return cfg


def search_queries(cfg):
    return list(dict.fromkeys(cfg["brand"] + cfg["intent"]))


# ---------------------------------------------------------------- classic search
BING_VARIANTS = ["", "&mkt=en-US", "&form=QBLH"]


def bing_url(q, first, variant=0):
    return f"https://www.bing.com/search?q={quote_plus(q)}" + (f"&first={first}" if first > 1 else "") + BING_VARIANTS[variant]


def unwrap_bing(href):
    """Bing often wraps result links in bing.com/ck/a?...&u=a1<base64url>."""
    href = unescape(href)
    if "bing.com/ck/a" in href:
        u = parse_qs(urlparse(href).query).get("u", [""])[0]
        if u.startswith("a1"):
            b = u[2:]
            b += "=" * (-len(b) % 4)
            try:
                return base64.urlsafe_b64decode(b).decode("utf-8", "replace")
            except Exception:
                return href
    return href


def parse_bing(html):
    if re.search(r"captcha|Verify you are human|/challenge", html[:20000], re.I) and "b_algo" not in html:
        raise Captcha("Bing returned a CAPTCHA/challenge page")
    urls = []
    for block in re.findall(r'<li class="b_algo".*?</li>', html, re.S):
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"', block, re.S)
        if m:
            urls.append((unwrap_bing(m.group(1)), unescape(re.sub(r"<[^>]+>", " ", block))))
    return urls


def parse_ddg(html):
    if "anomaly-modal" in html or "bots use DuckDuckGo too" in html or "Unfortunately, bots" in html:
        raise Captcha("DuckDuckGo returned a bot-check page")
    urls = []
    for href, rest in re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"(.*?)</a>', html, re.S):
        href = unescape(href)
        if "uddg=" in href:
            href = unquote(parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)["uddg"][0])
        urls.append((href, unescape(re.sub(r"<[^>]+>", " ", rest))))
    return urls


def relevant(q, items):
    """Bing sometimes serves unrelated decoy results to scripts. Count results whose url or
    text contains a query word of 4+ letters; fewer than 30% means the page is not trustworthy."""
    toks = [t for t in re.findall(r"[a-z0-9]+", q.lower()) if len(t) >= 4]
    if not items or not toks:
        return bool(items)
    hits = sum(any(t in (u + " " + x).lower() for t in toks) for u, x in items)
    return hits / len(items) >= 0.3


class Unreliable(Exception):
    pass


def run_search(engine, q, sess):
    items = []
    hdr = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    if engine == "bing":
        for variant in range(len(BING_VARIANTS)):
            items = []
            for first in (1, 11):
                if first > 1 or variant > 0:
                    time.sleep(SEARCH_DELAY)
                r = sess.get(bing_url(q, first, variant), headers=hdr, timeout=30)
                r.raise_for_status()
                got = [g for g in parse_bing(r.text) if g[0] not in [i[0] for i in items]]
                items += got
                if len(items) >= TOP_N or not got:
                    break
            if relevant(q, items):
                break
        else:
            raise Unreliable("Bing returned unrelated results (decoy page) on every attempt")
    else:
        r = sess.post("https://html.duckduckgo.com/html/", data={"q": q, "kl": "us-en"}, headers=hdr, timeout=30)
        r.raise_for_status()
        items = parse_ddg(r.text)
        if items and not relevant(q, items):
            raise Unreliable("DuckDuckGo returned unrelated results")
    return [u for u, _ in items][:TOP_N]


def do_search(cfg, queries, out):
    sess = requests.Session()
    res = {}
    stopped = {}
    first_req = True
    for engine in ENGINES:
        for q in queries:
            if engine in stopped:
                res[f"{engine}|{q}"] = {"status": "stopped", "note": stopped[engine]}
                continue
            if not first_req:
                time.sleep(SEARCH_DELAY)
            first_req = False
            try:
                urls = run_search(engine, q, sess)
            except Captcha as e:
                stopped[engine] = str(e)
                print(f"!! {engine}: {e}. Stopping {engine}; remaining queries skipped.")
                res[f"{engine}|{q}"] = {"status": "captcha", "note": str(e)}
                continue
            except Unreliable as e:
                res[f"{engine}|{q}"] = {"status": "unreliable", "note": str(e)}
                print(f"!! {engine} {q!r}: {e}")
                continue
            except requests.RequestException as e:
                res[f"{engine}|{q}"] = {"status": "error", "note": str(e)[:200]}
                print(f"!! {engine} '{q}': {e}")
                continue
            pos = next((i + 1 for i, u in enumerate(urls) if is_ours(u, cfg["domain"])), None)
            res[f"{engine}|{q}"] = {"status": "ok", "position": pos, "n_results": len(urls),
                                    "ours": [u for u in urls if is_ours(u, cfg["domain"])], "top": urls}
            print(f"   {engine:10s} {q!r}: {'pos ' + str(pos) if pos else 'none'} of {len(urls)}")
    out["search"] = res
    out["notes"].append("Brave Search skipped: it blocks bots. Google not scraped.")
    if stopped:
        out["notes"].append("Stopped early (bot check): " + "; ".join(f"{k}: {v}" for k, v in stopped.items()))


# ---------------------------------------------------------------- assistants
def post_json(url, headers, body):
    r = requests.post(url, headers=headers, json=body, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def ask_openai(q, key):
    j = post_json("https://api.openai.com/v1/responses",
                  {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                  {"model": MODELS["openai"], "input": q, "tools": [{"type": "web_search"}],
                   "max_output_tokens": MAX_TOKENS})
    text, urls, searches = "", [], 0
    for item in j.get("output", []):
        if item.get("type") == "web_search_call":
            searches += 1
        elif item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text":
                    text += c.get("text", "")
                    urls += [a["url"] for a in c.get("annotations", []) if a.get("type") == "url_citation"]
    u = j.get("usage", {})
    return text, urls, u.get("input_tokens", 0), u.get("output_tokens", 0), max(searches, 1)


def ask_perplexity(q, key):
    j = post_json("https://api.perplexity.ai/chat/completions",
                  {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                  {"model": MODELS["perplexity"], "messages": [{"role": "user", "content": q}],
                   "max_tokens": MAX_TOKENS})
    text = j["choices"][0]["message"]["content"]
    urls = list(j.get("citations") or []) + [s["url"] for s in j.get("search_results") or [] if s.get("url")]
    u = j.get("usage", {})
    return text, list(dict.fromkeys(urls)), u.get("prompt_tokens", 0), u.get("completion_tokens", 0), 1


def ask_anthropic(q, key):
    tool_type = os.environ.get("ANTHROPIC_WEB_SEARCH_TOOL", "web_search_20250305")
    j = post_json("https://api.anthropic.com/v1/messages",
                  {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                  {"model": MODELS["anthropic"], "max_tokens": MAX_TOKENS,
                   "thinking": {"type": "disabled"},
                   "tools": [{"type": tool_type, "name": "web_search", "max_uses": 3}],
                   "messages": [{"role": "user", "content": q}]})
    text, cited, seen = "", [], []
    for b in j.get("content", []):
        if b.get("type") == "text":
            text += b.get("text", "")
            cited += [c["url"] for c in b.get("citations") or [] if c.get("url")]
        elif b.get("type") == "web_search_tool_result" and isinstance(b.get("content"), list):
            seen += [r["url"] for r in b["content"] if r.get("url")]
    u = j.get("usage", {})
    searches = (u.get("server_tool_use") or {}).get("web_search_requests", 0)
    # Cited = urls the answer cites; fall back to urls the search returned if the model cited none.
    return text, list(dict.fromkeys(cited or seen)), u.get("input_tokens", 0), u.get("output_tokens", 0), searches


ASKERS = {"openai": ask_openai, "perplexity": ask_perplexity, "anthropic": ask_anthropic}


def do_assistants(cfg, out):
    res, total = {}, 0.0
    for prov, fn in ASKERS.items():
        key = os.environ.get(KEYS[prov])
        if not key:
            out["notes"].append(f"{prov}: skipped ({KEYS[prov]} not set)")
            print(f"-- {prov}: skipped ({KEYS[prov]} not set)")
            continue
        spent = 0.0
        for q in cfg["intent"]:
            try:
                text, urls, tin, tout, ns = fn(q, key)
            except Exception as e:
                res[f"{prov}|{q}"] = {"status": "error", "note": str(e)[:300]}
                print(f"!! {prov} '{q}': {e}")
                continue
            low = text.lower()
            cited_ours = [u for u in urls if is_ours(u, cfg["domain"])]
            mentioned = [t for t in cfg["product_terms"] if t.lower() in low]
            doms = list(dict.fromkeys(host_of(u) for u in urls if host_of(u)))
            p = PRICES[prov]
            cost = tin * p["in"] + tout * p["out"] + ns * p["per_search"]
            spent += cost
            res[f"{prov}|{q}"] = {
                "status": "ok", "model": MODELS[prov], "cited_ours": cited_ours, "mentioned_terms": mentioned,
                "cited_urls": urls, "cited_domains": doms,
                "competitor_domains": [d for d in doms if any(d == c or d.endswith("." + c) for c in cfg["competitors"])],
                "answer": text[:1500], "tokens_in": tin, "tokens_out": tout, "searches": ns, "est_cost_usd": round(cost, 5)}
            print(f"   {prov:10s} {q!r}: {cell_ai(res[f'{prov}|{q}'])}  (~${cost:.4f})")
        total += spent
        print(f"   {prov} estimated spend: ${spent:.4f}")
    out["assistants"] = res
    out["est_cost_usd"] = round(total, 4)
    print(f"Estimated total spend this run: ${total:.4f} (estimate from usage fields and list prices)")


# ---------------------------------------------------------------- Search Console (optional)
def do_gsc(cfg, out):
    cred = os.environ.get("GSC_CREDENTIALS")
    if not cred:
        out["notes"].append("Search Console skipped (GSC_CREDENTIALS not set)")
        print("-- Search Console: skipped (GSC_CREDENTIALS not set)")
        return
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
    except ImportError:
        out["notes"].append("Search Console skipped: pip install google-auth")
        print("-- Search Console: skipped (pip install google-auth)")
        return
    site = os.environ.get("GSC_SITE", f"sc-domain:{cfg['domain']}")
    try:
        creds = service_account.Credentials.from_service_account_file(
            cred, scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
        s = AuthorizedSession(creds)
        end = dt.date.today() - dt.timedelta(days=2)
        body = {"startDate": str(end - dt.timedelta(days=27)), "endDate": str(end), "dimensions": ["query"], "rowLimit": 250}
        r = s.post(f"https://www.googleapis.com/webmasters/v3/sites/{quote_plus(site)}/searchAnalytics/query", json=body)
        r.raise_for_status()
        rows = {x["keys"][0].lower(): x for x in r.json().get("rows", [])}
    except Exception as e:
        out["notes"].append(f"Search Console error: {str(e)[:200]}")
        print(f"!! Search Console: {e}")
        return
    res = {}
    for q in search_queries(cfg):
        x = rows.get(q.lower())
        res[f"google-gsc|{q}"] = ({"status": "ok", "impressions": x["impressions"], "clicks": x["clicks"],
                                    "position": round(x["position"], 1)} if x else
                                  {"status": "ok", "impressions": 0, "clicks": 0, "position": None})
    out["gsc"] = res
    print(f"   Search Console: {len(rows)} queries read, last 28 days")


# ---------------------------------------------------------------- output
def cell_search(r):
    if r["status"] != "ok":
        return r["status"]
    return str(r["position"]) if r["position"] else "none"


def cell_ai(r):
    if r["status"] != "ok":
        return "error"
    if r["cited_ours"]:
        return "cited"
    return "mentioned" if r["mentioned_terms"] else "absent"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def scoreboard(cfg, data):
    L = [f"# AI visibility scoreboard for {cfg['domain']}", "", f"Run date: {data['date']}", ""]
    if data.get("search"):
        L += [f"## Classic search (first position of {cfg['domain']} in top {TOP_N}; none = not found)", ""]
        rows = [[q] + [cell_search(data["search"][k]) if (k := f"{e}|{q}") in data["search"] else "-" for e in ENGINES]
                for q in search_queries(cfg)]
        L += [table(["Query"] + ENGINES, rows), ""]
    if data.get("gsc"):
        L += ["## Google Search Console (last 28 days)", ""]
        rows = [[q.split("|", 1)[1], str(v["impressions"]), str(v["clicks"]), str(v["position"] or "-")]
                for q, v in data["gsc"].items()]
        L += [table(["Query", "Impressions", "Clicks", "Avg position"], rows), ""]
    if data.get("assistants"):
        provs = [p for p in ASKERS if any(k.startswith(p + "|") for k in data["assistants"])]
        L += ["## AI assistants (cited = a minniai.com URL cited; mentioned = a product name in the answer)", ""]
        rows = [[q] + [cell_ai(data["assistants"][k]) if (k := f"{p}|{q}") in data["assistants"] else "-" for p in provs]
                for q in cfg["intent"]]
        L += [table(["Query"] + provs, rows), ""]
        comp = {}
        for r in data["assistants"].values():
            for d in r.get("cited_domains", []):
                comp[d] = comp.get(d, 0) + 1
        top = sorted(comp.items(), key=lambda x: -x[1])[:10]
        if top:
            L += ["### Most cited domains across all answers", "", table(["Domain", "Times cited"], [[d, str(n)] for d, n in top]), ""]
    if data.get("notes"):
        L += ["## Notes", ""] + [f"- {n}" for n in dict.fromkeys(data["notes"])] + [""]
    return "\n".join(L)


def history_rows(data):
    rows = []
    for k, r in data.get("search", {}).items():
        e, q = k.split("|", 1)
        rows.append([data["date"], "search", q, e, cell_search(r), r.get("position") or "", "", ""])
    for k, r in data.get("gsc", {}).items():
        q = k.split("|", 1)[1]
        rows.append([data["date"], "search", q, "google-gsc", r["position"] or "none", r["position"] or "", "", r["impressions"]])
    for k, r in data.get("assistants", {}).items():
        p, q = k.split("|", 1)
        rows.append([data["date"], "assistants", q, p, cell_ai(r), "", int(bool(r.get("cited_ours"))), int(bool(r.get("mentioned_terms")))])
    return rows


def write_outputs(cfg, data):
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{data['date']}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    board = scoreboard(cfg, data)
    (RESULTS / "scoreboard.md").write_text(board, encoding="utf-8")
    hist = RESULTS / "history.csv"
    head = ["date", "section", "query", "source", "result", "position", "cited", "mentioned_or_impressions"]
    old = []
    new = history_rows(data)
    if hist.exists():
        with hist.open(newline="", encoding="utf-8") as f:
            rd = list(csv.reader(f))
        redo = {(r[0], r[1], r[3]) for r in new}
        old = [r for r in rd[1:] if (r[0], r[1], r[3]) not in redo]
    with hist.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(old + new)
    return board


# ---------------------------------------------------------------- dry run
def dry_run(cfg, only):
    n = 0
    if only in (None, "search"):
        for e in ENGINES:
            for q in search_queries(cfg):
                n += 1
                if e == "bing":
                    print(f"[search] GET  {bing_url(q, 1)}  (+ first=11 if under {TOP_N} results)")
                else:
                    print(f"[search] POST https://html.duckduckgo.com/html/  q={q!r}")
        print(f"[search] wait {SEARCH_DELAY:.0f}s between requests; stop if a CAPTCHA page returns")
        print("[search] Brave: skipped (blocks bots); Google: not scraped")
        print("[search] Search Console: " + ("service account " + os.environ["GSC_CREDENTIALS"] if os.environ.get("GSC_CREDENTIALS")
                                              else "skipped (GSC_CREDENTIALS not set)"))
    if only in (None, "assistants"):
        for prov in ASKERS:
            have = "key found" if os.environ.get(KEYS[prov]) else f"WOULD SKIP, {KEYS[prov]} not set"
            for q in cfg["intent"]:
                n += 1
                ep = {"openai": "POST https://api.openai.com/v1/responses  tools=[web_search]",
                      "perplexity": "POST https://api.perplexity.ai/chat/completions",
                      "anthropic": "POST https://api.anthropic.com/v1/messages  tools=[web_search server tool]"}[prov]
                print(f"[assistant:{prov}] {ep} model={MODELS[prov]} max_tokens~{MAX_TOKENS} q={q!r}  ({have})")
    print(f"Dry run: {n} calls listed, no network used, nothing written.")


def main():
    ap = argparse.ArgumentParser(description="Weekly AI and search visibility scoreboard.")
    ap.add_argument("--queries", default=str(HERE / "queries.yaml"))
    ap.add_argument("--only", choices=["search", "assistants"])
    ap.add_argument("--dry-run", action="store_true", help="print the calls, make none")
    a = ap.parse_args()
    cfg = load_cfg(a.queries)
    if a.dry_run:
        dry_run(cfg, a.only)
        return 0
    date = dt.date.today().isoformat()
    jf = RESULTS / f"{date}.json"
    data = {"date": date, "domain": cfg["domain"], "notes": []}
    if jf.exists():  # merge with an earlier partial run of the same day
        try:
            data = {**json.loads(jf.read_text(encoding="utf-8")), "notes": []}
        except ValueError:
            pass
    if a.only in (None, "search"):
        print("== Classic search ==")
        do_search(cfg, search_queries(cfg), data)
        do_gsc(cfg, data)
    if a.only in (None, "assistants"):
        print("== AI assistants ==")
        do_assistants(cfg, data)
    print()
    print(write_outputs(cfg, data))
    print(f"\nWrote {jf}, {RESULTS / 'scoreboard.md'}, {RESULTS / 'history.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
