"""Turn a contractor estimate PDF into a mobile-friendly, self-contained HTML page.

Usage:
    py -3 estimate_page.py <estimate.pdf> [more.pdf ...] [--out DIR] [--json-only]
    py -3 estimate_page.py --from-json <job.json> [--out DIR]

Each PDF becomes <out>/<pdf name>.html plus <pdf name>.json (the parsed data).
If the parse is wrong, fix the JSON by hand and rebuild with --from-json.
The run fails (exit 1) when the line items, subtotal, tax and total don't add up.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote

import fitz  # PyMuPDF

DEFAULT_OUT = Path(r"C:\Users\hamza\Desktop\Claude Files\Estimate Pages")
LOGO_URI = re.compile(r"data:image/(png|jpe?g|gif|webp);base64,[A-Za-z0-9+/=]+")
MONEY = re.compile(r"^\$[\d,]+\.\d{2}$")
PRICE_WORDS = {"included", "n/c", "no charge", "free", "tbd"}

# Area tag shown above each scope card, picked from the item title.
AREAS = [
    ("garage", "Garage"), ("attic", "Attic"), ("porch", "Porch"), ("basement", "Basement"),
    ("crawl", "Crawl Space"), ("wall", "Walls"), ("ceiling", "Ceiling"), ("roof", "Roof"),
    ("bath", "Bathroom"), ("floor", "Floor"), ("rim joist", "Rim Joists"),
]


# ---------------------------------------------------------------- parsing
def money(s: str) -> float | None:
    s = s.strip()
    return float(s.replace("$", "").replace(",", "")) if MONEY.match(s) else None


def is_price(line: str) -> bool:
    return bool(MONEY.match(line)) or line.strip().lower() in PRICE_WORDS


def is_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


def parse_pdf(pdf: Path) -> dict:
    doc = fitz.open(pdf)
    lines = [ln.strip() for page in doc for ln in page.get_text("text").splitlines() if ln.strip()]

    def find(pred, start=0):
        for i in range(start, len(lines)):
            if pred(lines[i]):
                return i
        raise ValueError(f"{pdf.name}: could not find expected section after line {start}")

    title_i = find(lambda l: l in {"ESTIMATE", "QUOTE", "INVOICE", "PROPOSAL"})
    company_lines = lines[:title_i]
    company = {"name": company_lines[0] if company_lines else "", "address": [], "phone": "", "email": ""}
    for l in company_lines[1:]:
        if "@" in l:
            company["email"] = l
        elif re.fullmatch(r"[\d\s().+-]{10,}", l):
            company["phone"] = l
        else:
            company["address"].append(l)

    meta = {}
    i = title_i + 1
    while i < len(lines) and ":" in lines[i] and not is_heading(lines[i]):
        k, v = lines[i].split(":", 1)
        meta[k.strip()] = v.strip()
        i += 1

    # Client block and overview: headings come first, then client lines up to "Phone:", then overview.
    hdr = find(lambda l: l.upper().startswith("CLIENT"), i)
    j = hdr + 1
    if lines[j].upper().startswith("PROJECT"):
        j += 1
    table_i = find(lambda l: l == "#" or l.upper().startswith("DESCRIPTION"), j)
    block = lines[j:table_i]
    phone_i = next((k for k, l in enumerate(block) if l.lower().startswith("phone")), None)
    if phone_i is None:  # no phone line: assume name + one address line
        phone_i = min(1, len(block) - 1)
    client_lines = block[: phone_i + 1]
    overview = " ".join(block[phone_i + 1:])
    client = {"name": client_lines[0] if client_lines else "", "address": [], "phone": ""}
    for l in client_lines[1:]:
        if l.lower().startswith("phone"):
            client["phone"] = l.split(":", 1)[-1].strip()
        else:
            client["address"].append(l)

    # Line items: number, title, description lines, price.
    k = table_i
    while k < len(lines) and not lines[k].isdigit():
        k += 1
    items = []
    while k < len(lines) and lines[k].isdigit():
        num = int(lines[k])
        p = k + 1
        while p < len(lines) and not is_price(lines[p]):
            p += 1
        body = lines[k + 1: p]
        items.append({
            "num": num,
            "title": body[0] if body else "",
            "description": " ".join(body[1:]),
            "price": lines[p] if p < len(lines) else "",
        })
        k = p + 1

    # Totals: label line followed by an amount.
    totals = []
    while k + 1 < len(lines) and money(lines[k + 1]) is not None:
        totals.append({"label": lines[k], "amount": lines[k + 1]})
        k += 2

    # Notices: ALL-CAPS heading, then paragraph until the next heading.
    notices = []
    while k < len(lines):
        if is_heading(lines[k]):
            notices.append({"title": lines[k], "body": ""})
        elif notices:
            notices[-1]["body"] = (notices[-1]["body"] + " " + lines[k]).strip()
        k += 1

    logo = ""
    imgs = doc[0].get_images(full=True)
    if imgs:
        x = doc.extract_image(imgs[0][0])
        logo = f"data:image/{x['ext']};base64," + base64.b64encode(x["image"]).decode()

    return {
        "source_pdf": pdf.name, "doc_type": lines[title_i].title(), "company": company,
        "meta": meta, "client": client, "overview": overview,
        "items": items, "totals": totals, "notices": notices, "logo": logo,
    }


def check_math(job: dict) -> list[str]:
    """Return a list of problems; empty means the numbers add up."""
    errs = []
    if not job["items"]:
        errs.append("no line items found")
    item_sum = sum(money(it["price"]) or 0 for it in job["items"])
    t = {x["label"].upper(): money(x["amount"]) for x in job["totals"]}
    sub = next((v for k, v in t.items() if "SUBTOTAL" in k), None)
    tax = next((v for k, v in t.items() if any(w in k for w in ("HST", "GST", "TAX", "PST"))), None)
    total = next((v for k, v in t.items() if "TOTAL" in k and "SUB" not in k), None)
    if total is None:
        errs.append("no total found")
    if sub is not None and abs(sub - item_sum) > 0.01:
        errs.append(f"items add to {item_sum:,.2f} but subtotal is {sub:,.2f}")
    if None not in (sub, tax, total) and abs(sub + tax - total) > 0.01:
        errs.append(f"subtotal + tax = {sub + tax:,.2f} but total is {total:,.2f}")
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", " ".join(t))
    if m and sub is not None and tax is not None and abs(round(sub * float(m.group(1)) / 100, 2) - tax) > 0.01:
        errs.append(f"tax {tax:,.2f} is not {m.group(1)}% of {sub:,.2f}")
    return errs


# ---------------------------------------------------------------- rendering
def area_of(title: str) -> str:
    low = title.lower()
    return next((name for key, name in AREAS if key in low), "Scope of Work")


def label(s: str) -> str:
    """'HST (13%)' stays 'HST (13%)', 'SUBTOTAL' becomes 'Subtotal'."""
    keep = {"HST", "GST", "PST", "QST", "CAD"}
    return " ".join(w if w.strip("()") in keep else w.capitalize() for w in (s or "").split())


def e(s: str) -> str:
    return html.escape(s or "")


def digits(s: str) -> str:
    return re.sub(r"[^\d+]", "", s or "")


def render(job: dict) -> str:
    c, cl, meta = job["company"], job["client"], job["meta"]
    total = next((x for x in job["totals"] if "TOTAL" in x["label"].upper() and "SUB" not in x["label"].upper()),
                 job["totals"][-1] if job["totals"] else {"label": "Total", "amount": ""})
    est_no = meta.get("Estimate #") or meta.get("Quote #") or next(iter(meta.values()), "")
    date = meta.get("Date", "")
    valid = meta.get("Valid Until", "")
    addr = cl["address"][0] if cl["address"] else cl["name"]
    subject = f"Booking {job['doc_type'].lower()} {est_no} - {addr}"
    mail = f"mailto:{quote(c['email'], safe='@.+-_')}?subject={quote(subject)}" if c["email"] else ""
    tel = f"tel:{digits(c['phone'])}" if c["phone"] else ""
    book_href = mail or tel or "#"

    cards = []
    for it in job["items"]:
        price = it["price"]
        included = money(price) is None
        cards.append(f"""
    <article class="card scope">
      <div class="scope-top">
        <span class="area">📍 {e(area_of(it['title']))}</span>
        <span class="num">{it['num']:02d}</span>
      </div>
      <h3>{e(it['title'])}</h3>
      <p>{e(it['description'])}</p>
      <div class="price{' incl' if included else ''}">{e('✓ ' + price if included else price)}</div>
    </article>""")

    total_rows = "".join(
        f'<div class="trow{" grand" if x is total else ""}"><span>{e(label(x["label"]) if x is not total else x["label"])}</span>'
        f'<b>{e(x["amount"])}</b></div>' for x in job["totals"])

    notices = "".join(f"""
    <article class="card notice">
      <div class="eyebrow warn">⚠ Before we start</div>
      <h3>{e(n['title'].title())}</h3>
      <p>{e(n['body'])}</p>
    </article>""" for n in job["notices"])

    logo_ok = bool(LOGO_URI.fullmatch(job.get("logo") or ""))
    logo = f'<img src="{e(job["logo"])}" alt="{e(c["name"])} logo">' if logo_ok else ""
    company_addr = "<br>".join(e(a) for a in c["address"])
    n_items = len(job["items"])
    areas = list(dict.fromkeys(area_of(it["title"]) for it in job["items"]))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#092454">
<title>{e(c['name'])} — {e(addr)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Poppins:wght@600;700;800&display=swap" rel="stylesheet">
<style>
:root {{
  --navy:#092454; --navy-2:#13306b; --pink:#e2457f; --pink-soft:#fdeef3;
  --ink:#16213a; --muted:#5d6a85; --line:#e3e8f2; --bg:#dfe4ec; --card:#fff; --ok:#1f8a5b;
}}
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{ background:var(--bg); color:var(--ink); font:15px/1.55 Inter,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }}
.wrap {{ max-width:440px; margin:0 auto; background:#f4f6fa; min-height:100vh; padding-bottom:110px; box-shadow:0 0 40px rgba(9,36,84,.08); }}
header.brand {{ display:flex; align-items:center; justify-content:center; gap:10px; padding:12px 16px; background:#fff; border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }}
header.brand img {{ height:40px; }}
header.brand span {{ font:700 15px Poppins,sans-serif; color:var(--navy); letter-spacing:.2px; }}
main {{ padding:12px; display:flex; flex-direction:column; gap:12px; }}
.card {{ background:var(--card); border-radius:18px; padding:18px; box-shadow:0 1px 2px rgba(9,36,84,.06),0 4px 14px rgba(9,36,84,.05); }}
.hero {{ background:radial-gradient(120% 90% at 100% 0%, var(--navy-2), var(--navy) 60%); color:#fff; padding:22px 20px; position:relative; overflow:hidden; }}
.hero::after {{ content:""; position:absolute; right:-50px; top:-50px; width:150px; height:150px; border-radius:50%; background:var(--pink); opacity:.16; }}
.hero > * {{ position:relative; z-index:1; }}
.eyebrow {{ font:700 11px Inter,sans-serif; letter-spacing:1.2px; text-transform:uppercase; }}
.hero .eyebrow {{ display:inline-block; background:rgba(255,255,255,.14); padding:5px 10px; border-radius:999px; }}
.hero .kind {{ margin-top:16px; color:#ffc2d6; }}
.hero .kind::before {{ content:"●"; color:var(--pink); margin-right:6px; }}
.hero h1 {{ font:800 28px/1.15 Poppins,sans-serif; margin:6px 0 4px; text-transform:capitalize; }}
.hero .who {{ opacity:.85; font-size:14px; }}
.hero .meta {{ display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:16px; font-size:12.5px; opacity:.9; }}
.hero .big {{ margin-top:18px; padding-top:14px; border-top:1px solid rgba(255,255,255,.18); display:flex; justify-content:space-between; align-items:end; }}
.hero .big small {{ display:block; font-size:11px; letter-spacing:1px; text-transform:uppercase; opacity:.75; }}
.hero .big b {{ font:800 26px Poppins,sans-serif; }}
.hero .big em {{ font-style:normal; font-size:12px; opacity:.8; text-align:right; }}
h2 {{ font:700 18px Poppins,sans-serif; color:var(--navy); margin:2px 0 6px; }}
.card h3 {{ font:700 16.5px/1.3 Poppins,sans-serif; color:var(--navy); margin:8px 0 6px; }}
.card p {{ color:var(--muted); }}
.overview .eyebrow, .section-label {{ color:var(--pink); }}
.section-label {{ padding:8px 6px 0; }}
.section-label + .sub {{ padding:0 6px; color:var(--muted); font-size:13px; margin-top:-8px; }}
.scope-top {{ display:flex; justify-content:space-between; align-items:center; }}
.area {{ font-size:12px; font-weight:600; color:var(--muted); }}
.num {{ font:700 12px Poppins,sans-serif; color:#a9b3c7; }}
.price {{ margin-top:12px; display:inline-block; font:700 15px Poppins,sans-serif; color:var(--navy); background:#eef2f9; padding:6px 12px; border-radius:10px; }}
.price.incl {{ color:var(--ok); background:#e6f5ee; }}
.totals .trow {{ display:flex; justify-content:space-between; padding:10px 0; border-bottom:1px solid var(--line); color:var(--muted); }}
.totals .trow b {{ color:var(--ink); }}
.totals .trow.grand {{ border:0; margin:8px -18px -18px; padding:16px 18px; background:var(--navy); color:#fff; border-radius:0 0 18px 18px; font:700 14px Poppins,sans-serif; letter-spacing:.4px; }}
.totals .trow.grand b {{ color:#fff; font-size:22px; }}
.notice {{ background:var(--pink-soft); border:1px solid #f6c3d5; }}
.notice .warn {{ color:var(--pink); }}
.notice p {{ color:#5a3a47; }}
.company {{ text-align:center; }}
.company img {{ height:84px; margin-bottom:6px; }}
.company .name {{ font:700 17px Poppins,sans-serif; color:var(--navy); }}
.company .addr {{ color:var(--muted); font-size:13px; margin:4px 0 14px; }}
.contact {{ display:flex; flex-direction:column; gap:8px; }}
.contact a {{ display:block; padding:12px; border-radius:12px; border:1px solid var(--line); color:var(--navy); text-decoration:none; font-weight:600; word-break:break-word; }}
.fine {{ text-align:center; color:#8a94aa; font-size:12px; padding:4px 12px 0; }}
.cta {{ position:fixed; left:0; right:0; bottom:0; padding:12px 12px calc(12px + env(safe-area-inset-bottom)); background:linear-gradient(to top, rgba(244,246,250,1) 60%, rgba(244,246,250,0)); }}
.cta a {{ display:block; max-width:416px; margin:0 auto; text-align:center; background:var(--navy); color:#fff; text-decoration:none; font:700 15px Poppins,sans-serif; padding:15px; border-radius:14px; box-shadow:0 8px 20px rgba(9,36,84,.3); }}
@media print {{ .cta, header.brand {{ display:none }} body,.wrap {{ background:#fff; box-shadow:none }} }}
</style>
</head>
<body>
<div class="wrap">
  <header class="brand">{logo}<span>{e(c['name'])}</span></header>
  <main>
    <section class="card hero">
      <span class="eyebrow">{e(job['doc_type'])}</span>
      <div class="eyebrow kind">{e(' · '.join(areas))}</div>
      <h1>{e(addr)}</h1>
      <div class="who">Prepared for {e(cl['name'])}{(' · ' + e(cl['phone'])) if cl['phone'] else ''}</div>
      <div class="meta">
        {f'<span>📅 {e(date)}</span>' if date else ''}
        {f'<span>#️⃣ {e(est_no)}</span>' if est_no else ''}
      </div>
      <div class="big">
        <div><small>{e(label(total['label']))}</small><b>{e(total['amount'])}</b></div>
        {f'<em>Valid until<br>{e(valid)}</em>' if valid else ''}
      </div>
    </section>

    {f'''<section class="card overview">
      <div class="eyebrow">Project overview</div>
      <h2>What we'll do</h2>
      <p>{e(job['overview'])}</p>
    </section>''' if job['overview'] else ''}

    <div class="eyebrow section-label">Scope of work</div>
    <div class="sub">{n_items} item{'s' if n_items != 1 else ''} · prices in CAD</div>
    {''.join(cards)}

    <section class="card totals">
      <div class="eyebrow section-label" style="padding:0 0 4px">Your investment</div>
      {total_rows}
    </section>
    {notices}

    <section class="card company">
      {logo}
      <div class="name">{e(c['name'])}</div>
      <div class="addr">{company_addr}</div>
      <div class="contact">
        {f'<a href="{e(tel)}">📞 {e(c["phone"])}</a>' if tel else ''}
        {f'<a href="{e(mail)}">✉ {e(c["email"])}</a>' if c['email'] else ''}
      </div>
    </section>
    <p class="fine">{e(job['doc_type'])} {e(est_no)}{(' · valid until ' + e(valid)) if valid else ''}</p>
  </main>
  <div class="cta"><a href="{e(book_href)}">Book your job now · {e(total['amount'])} →</a></div>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------- cli
def build(job: dict, out: Path, stem: str, json_only: bool) -> int:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    errs = check_math(job)
    if errs:
        print(f"FAIL {stem}: " + "; ".join(errs) + f"\n  fix {out / (stem + '.json')} and rerun with --from-json")
        return 1
    if not json_only:
        (out / f"{stem}.html").write_text(render(job), encoding="utf-8")
        print(f"OK   {out / (stem + '.html')}  ({len(job['items'])} items, numbers add up)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdfs", nargs="*", type=Path)
    ap.add_argument("--from-json", type=Path)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--json-only", action="store_true", help="parse and check, don't write HTML")
    a = ap.parse_args()
    if a.from_json:
        job = json.loads(a.from_json.read_text(encoding="utf-8"))
        return build(job, a.out, a.from_json.stem, a.json_only)
    if not a.pdfs:
        ap.print_help()
        return 2
    rc = 0
    for pdf in a.pdfs:
        try:
            rc |= build(parse_pdf(pdf), a.out, pdf.stem, a.json_only)
        except Exception as ex:  # keep going on a batch
            print(f"FAIL {pdf.name}: {ex}")
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
