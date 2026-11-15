# EstimatePageGenerator

Turns a contractor estimate PDF into a clean, phone-friendly web page: one self-contained `.html` file you can text, email or host anywhere.

The page shows the job address and total up front, a project overview, one card per line item, the subtotal / tax / total, any notices from the PDF, the company's contact details, and a sticky **Book your job now** button (opens an email to the company with the estimate number in the subject).

## Run it

Needs Python 3.10+ and PyMuPDF (`py -3 -m pip install pymupdf`).

```
py -3 estimate_page.py "C:\path\to\Some_Estimate.pdf"
```

Several PDFs at once:

```
py -3 estimate_page.py a.pdf b.pdf c.pdf
```

Output goes to `C:\Users\hamza\Desktop\Claude Files\Estimate Pages\` by default (change with `--out DIR`). Each PDF gives two files:

- `<name>.html`: the page. Self-contained (logo embedded); fonts load from Google Fonts with a system-font fallback offline.
- `<name>.json`: what the script read from the PDF.

## When the parse is wrong

Edit the `.json` and rebuild from it:

```
py -3 estimate_page.py --from-json "C:\...\Estimate Pages\Some_Estimate.json"
```

## Safety check

Every run checks that the line items add up to the subtotal, that subtotal + tax = total, and that the tax matches its stated percent. If not, it prints `FAIL` with the reason, writes only the `.json`, and exits with code 1. No page is made from numbers that don't add up.

## What PDFs it reads

Built for the Prolific Insulation estimate layout: company block, `ESTIMATE` title, `Key: value` lines (Estimate #, Date, Valid Until), client info + project overview, a numbered scope table with prices (or `Included`), totals, and ALL-CAPS notices. A different layout will likely need parser changes.

## Side effects

Reads the PDF, writes two files to the output folder. No network calls, nothing installed, nothing else touched.

Disclaimer: provided as-is. Always check the page against the original PDF before sending it to a client.
