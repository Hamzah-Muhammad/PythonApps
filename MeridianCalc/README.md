# Meridian

A calculator for Windows built for long-form math. What you type shows like a textbook:
fractions stack numerator over denominator, powers sit raised, square roots get a real radical sign.
The answer updates live as you type. Math stays exact (3/4 stays 3/4) until a root or a decimal power needs rounding.

## Buttons

| Button | Does |
|---|---|
| Fraction (`▯/▯`) | Adds a stacked fraction. Type the top, press ↓ (or →) to move to the bottom, → to leave it |
| Dial | Moves the cursor. ← → step through everything, including in and out of fractions. ↑ ↓ jump between top and bottom of a fraction (outside one: line start / end) |
| `DEL` | Deletes left of the cursor. Next to a filled fraction or root it steps inside first, so nothing vanishes by surprise |
| `AC` | Clears the line. Press again on an empty line to clear the history |
| `x²` `xʸ` `√` | Square, any power, square root |
| `%` | Percent (`50% × 80 = 40`) |
| `Ans` | The last answer. Pressing an operator right after `=` continues from it |
| `=` | Calculate. Exact answers that are fractions also show the fraction form |

Brackets close themselves at the end, and `2(3+4)` or `3√4` multiply without a `×`.

**Mouse:** click anywhere in the expression to put the cursor there. Click a past calculation to load it back
for editing. Scroll the screen to see older history.

## Keyboard

| Key | Does |
|---|---|
| `0-9` `.` `+` `-` `*` `/` `(` `)` `%` | Type as normal |
| `_` | Fraction |
| `^` / `s` | Power / square |
| `r` | Square root |
| `a` | Ans |
| `Enter` or `=` | Calculate |
| `Backspace` / `Esc` | DEL / AC |
| Arrows, `Home`, `End` | Move the cursor |
| `Ctrl+C` | Copy the answer |

## Run it

Double-click `dist\Meridian.exe` (or the Desktop shortcut). From source:

```
pip install pygame
python meridian.py
```

## Build the exe

```
pip install pyinstaller pillow
python make_icon.py
pyinstaller --noconfirm --onefile --windowed --name Meridian --icon icon.ico --add-data "icon.png;." meridian.py
```

The exe lands in `dist\`. PyInstaller binaries sometimes trigger antivirus false positives;
build it yourself from this source if in doubt.

No warranty. Use at your own risk.
