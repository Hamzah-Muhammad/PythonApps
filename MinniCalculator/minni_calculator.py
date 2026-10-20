"""Minni Calculator: a calculator for long-form math with textbook display.

Fractions stack (numerator over denominator), powers sit raised, roots get a real radical.
Arithmetic is exact (fractions.Fraction) until a root or a fractional power forces a float.
"""
import ctypes
import math
import os
import sys
import time
from fractions import Fraction

import pygame

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
ICON_PATH = os.path.join(HERE, "icon.png")

# Palette shared with Nocturne: black lacquer, ivory, burgundy felt, brushed gold
LACQUER_TOP, LACQUER_BOTTOM = (24, 22, 26), (7, 7, 9)
GOLD, GOLD_MUTED, GOLD_DIM = (206, 174, 102), (150, 128, 82), (78, 66, 44)
IVORY_TEXT, IVORY_MUTED, FAINT = (238, 232, 216), (176, 170, 156), (122, 114, 100)
FELT_TOP, FELT_BOTTOM = (122, 24, 36), (78, 12, 22)
ERROR = (214, 120, 112)
SCREEN_BG = (10, 10, 12)

DIGITS = set("0123456789.")
BINOPS = {"+", "−", "×", "÷"}
MAX_EXACT_DIGITS = 20000  # past this an exact power would take ages; fall back to floats


# ---------- expression model ----------

class Row:
    """A horizontal run of items: single-character strings, 'Ans', or Nodes."""

    def __init__(self, parent=None):
        self.items = []
        self.parent = parent  # (node, slot index) or None for the top line


class Node:
    """A 2-D structure: frac (numerator, denominator), pow (exponent), sqrt (body)."""

    SLOTS = {"frac": 2, "pow": 1, "sqrt": 1}

    def __init__(self, kind):
        self.kind = kind
        self.slots = [Row((self, i)) for i in range(self.SLOTS[kind])]
        self.row = None  # the Row this node sits in

    def empty(self):
        return all(not s.items for s in self.slots)


def clone_row(row, parent=None):
    new = Row(parent)
    for it in row.items:
        if isinstance(it, Node):
            node = Node(it.kind)
            node.slots = [clone_row(s, (node, i)) for i, s in enumerate(it.slots)]
            node.row = new
            new.items.append(node)
        else:
            new.items.append(it)
    return new


def make_row(*items):
    row = Row()
    for it in items:
        if isinstance(it, Node):
            it.row = row
        row.items.append(it)
    return row


def node_with(kind, *slot_texts):
    node = Node(kind)
    for slot, text in zip(node.slots, slot_texts):
        slot.items.extend(text)
    return node


# ---------- evaluation ----------

class CalcError(Exception):
    pass


def evaluate(row, ans):
    try:
        return Parser(row, ans).run()
    except ZeroDivisionError:
        raise CalcError("Can't divide by zero")
    except OverflowError:
        raise CalcError("Too large")


class Parser:
    """Recursive descent: + − over × ÷ (and implied ×) over unary − over % and powers."""

    def __init__(self, row, ans):
        self.ans = ans
        self.toks = self.tokenize(row)
        self.pos = 0

    @staticmethod
    def tokenize(row):
        out, items, i = [], row.items, 0
        while i < len(items):
            it = items[i]
            if isinstance(it, Node):
                out.append(("pow", it.slots[0]) if it.kind == "pow" else ("node", it))
                i += 1
            elif it in DIGITS:
                j = i
                while j < len(items) and isinstance(items[j], str) and items[j] in DIGITS:
                    j += 1
                out.append(("num", "".join(items[i:j])))
                i = j
            elif it == "Ans":
                out.append(("ans", None))
                i += 1
            else:
                out.append(("op", it))
                i += 1
        return out

    def run(self):
        if not self.toks:
            raise CalcError("Nothing to calculate")
        value = self.expr()
        if self.peek_op(")"):  # stray closing bracket
            raise CalcError("Unmatched bracket")
        if self.pos < len(self.toks):
            raise CalcError("Syntax error")
        return value

    def peek(self):
        return self.toks[self.pos] if self.pos < len(self.toks) else (None, None)

    def peek_op(self, *ops):
        kind, val = self.peek()
        return kind == "op" and val in ops

    def take(self):
        tok = self.peek()
        self.pos += 1
        return tok

    def expr(self):
        value = self.term()
        while self.peek_op("+", "−"):
            op = self.take()[1]
            rhs = self.term()
            value = value + rhs if op == "+" else value - rhs
        return value

    def term(self):
        value = self.unary()
        while True:
            if self.peek_op("×", "÷"):
                op = self.take()[1]
                rhs = self.unary()
                value = value * rhs if op == "×" else value / rhs
            elif self.starts_atom():  # 2(3), 3√4, 2Ans: implied multiplication
                value = value * self.unary()
            else:
                return value

    def starts_atom(self):
        kind, val = self.peek()
        return kind in ("num", "ans", "node") or (kind == "op" and val == "(")

    def unary(self):
        if self.peek_op("−"):
            self.take()
            return -self.unary()
        if self.peek_op("+"):
            self.take()
            return self.unary()
        return self.postfix()

    def postfix(self):
        value = self.atom()
        while True:
            kind, val = self.peek()
            if kind == "op" and val == "%":
                self.take()
                value = value / 100
            elif kind == "pow":
                self.take()
                value = power(value, Parser(val, self.ans).run())
            else:
                return value

    def atom(self):
        kind, val = self.take()
        if kind == "num":
            try:
                return Fraction(val)
            except ValueError:
                raise CalcError("Syntax error")
        if kind == "ans":
            return self.ans
        if kind == "node":
            if val.kind == "frac":
                num, den = (Parser(s, self.ans).run() for s in val.slots)
                return num / den
            return square_root(Parser(val.slots[0], self.ans).run())
        if kind == "op" and val == "(":
            value = self.expr()
            if self.peek_op(")"):
                self.take()
            elif self.pos < len(self.toks):
                raise CalcError("Syntax error")
            return value  # a bracket left open at the end closes itself
        if kind == "pow":
            raise CalcError("Power needs a base")
        raise CalcError("Syntax error")


def power(base, exp):
    if isinstance(base, Fraction) and isinstance(exp, Fraction) and exp.denominator == 1:
        size = (len(str(abs(base.numerator))) + len(str(base.denominator))) * abs(exp.numerator)
        if size <= MAX_EXACT_DIGITS:
            return base ** exp.numerator
    b, e = float(base), float(exp)
    if b < 0 and not e.is_integer():
        # odd roots of negatives are real: (−8)^(1/3) = −2
        if isinstance(exp, Fraction) and exp.denominator % 2 == 1:
            magnitude = (-b) ** e
            return -magnitude if exp.numerator % 2 else magnitude
        raise CalcError("No real answer")
    return b ** e


def square_root(x):
    if x < 0:
        raise CalcError("No real answer")
    if isinstance(x, Fraction):
        n, d = math.isqrt(x.numerator), math.isqrt(x.denominator)
        if n * n == x.numerator and d * d == x.denominator:
            return Fraction(n, d)
    return math.sqrt(x)


def format_number(v):
    if isinstance(v, Fraction) and v.denominator == 1:
        n = v.numerator
        if abs(n) < 10 ** 15:
            return f"{n:,}"
        digits = str(abs(n))
        mantissa = (digits[0] + "." + digits[1:11]).rstrip("0").rstrip(".")
        return f"{'-' if n < 0 else ''}{mantissa}E{len(digits) - 1}"
    try:
        f = float(v)
    except OverflowError:
        raise CalcError("Too large")
    if not math.isfinite(f):
        raise CalcError("Too large")
    if f == 0:
        return "0"
    a = abs(f)
    if 1e-9 <= a < 1e15:
        decimals = max(0, 11 - math.floor(math.log10(a)))
        text = f"{f:,.{decimals}f}"
        return text.rstrip("0").rstrip(".") if "." in text else text
    mantissa, exp = f"{f:.10e}".split("e")
    return f"{mantissa.rstrip('0').rstrip('.')}E{int(exp)}"


def fraction_form(v):
    """A stacked-fraction Row for exact non-integer results with a readable denominator."""
    if isinstance(v, Fraction) and v.denominator != 1 and v.denominator <= 100000:
        frac = node_with("frac", str(abs(v.numerator)), str(v.denominator))
        return make_row("−", frac) if v < 0 else make_row(frac)
    return None


# ---------- drawing helpers ----------

def vertical_gradient(size, top, bottom):
    w, h = size
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        t = y / max(1, h - 1)
        pygame.draw.line(surf, [round(a + (b - a) * t) for a, b in zip(top, bottom)], (0, y), (w, y))
    return surf


def rounded(surf, radius):
    mask = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return surf


class Button:
    def __init__(self, label, action, rect, style):
        self.label, self.action, self.rect, self.style = label, action, rect, style


STYLES = {  # face top, face bottom, text colour
    "num": ((50, 47, 54), (26, 25, 29), IVORY_TEXT),
    "op": ((44, 41, 47), (22, 21, 25), GOLD),
    "fn": ((38, 36, 41), (19, 18, 22), GOLD_MUTED),
    "warn": (FELT_TOP, FELT_BOTTOM, IVORY_TEXT),
    "eq": ((222, 192, 120), (176, 144, 78), (20, 18, 16)),
    "frac": ((58, 50, 36), (30, 26, 20), GOLD),
}


class App:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Hamzah.Minni.Calculator")
        except (AttributeError, OSError):
            pass
        os.environ["SDL_VIDEO_CENTERED"] = "1"
        pygame.display.init()
        pygame.font.init()

        info = pygame.display.Info()
        base_w, base_h = 380, 872
        self.s = min(1.4, 0.85 * info.current_h / base_h, 0.5 * info.current_w / base_w)
        s = self.s
        self.width, self.height = round(base_w * s), round(base_h * s)
        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Minni Calculator")
        if os.path.exists(ICON_PATH):
            pygame.display.set_icon(pygame.image.load(ICON_PATH))
        pygame.key.set_repeat(380, 45)

        self.serif_path = pygame.font.match_font("palatinolinotype,georgia,timesnewroman")
        self.sans_path = pygame.font.match_font("segoeui,arial")
        self.fonts, self.glyphs = {}, {}
        self.placeholder_color = None  # empty-slot boxes: dim on screen, full colour on buttons
        self.f_title = pygame.font.Font(self.serif_path, round(30 * s))
        self.f_caps = pygame.font.Font(self.serif_path, round(10 * s))
        self.f_label = pygame.font.Font(self.serif_path, round(17 * s))
        self.f_op_label = pygame.font.Font(self.serif_path, round(25 * s))
        self.f_hint = pygame.font.Font(self.sans_path, round(11 * s))

        self.background = vertical_gradient((self.width, self.height), LACQUER_TOP, LACQUER_BOTTOM)
        self.margin = round(20 * s)
        self.panel = pygame.Rect(self.margin, round(64 * s), self.width - 2 * self.margin, round(250 * s))
        self.build_buttons()
        self.face_cache = {}

        self.expr = Row()
        self.row, self.idx = self.expr, 0
        self.ans = Fraction(0)
        self.history = []        # (expression Row, value or None, error text or None)
        self.history_scroll = 0  # entries hidden below the bottom of the history area
        self.history_hits = []   # (rect, entry) from the last frame, for click-to-recall
        self.result = None       # (value, error) shown after =
        self.preview = None
        self.scroll_x = 0
        self.carets = []
        self.pressed = None      # button held with the mouse
        self.flash = {}          # action -> time, for keyboard presses
        self.dial_pressed = None
        self.last_input = time.time()

    # ---------- layout ----------

    def build_buttons(self):
        s, m = self.s, self.margin
        gap = round(10 * s)
        bw = (self.width - 2 * m - 3 * gap) / 4
        bh = round(54 * s)
        top = self.panel.bottom + round(16 * s)

        def cell(col, row, span=1):
            x = round(m + col * (bw + gap))
            return pygame.Rect(x, round(top + row * (bh + gap)), round(span * bw + (span - 1) * gap), bh)

        zone = cell(0, 0, 2).union(cell(0, 1, 2))
        self.dial_center = zone.center
        self.dial_r = min(zone.w, zone.h) / 2
        x_row = make_row("x", node_with("pow", "2"))
        xy_row = make_row("x", node_with("pow", "y"))
        layout = [
            ("DEL", "del", 2, 0, 1, "warn"), ("AC", "clear", 3, 0, 1, "warn"),
            (make_row(Node("frac")), "frac", 2, 1, 1, "frac"), (make_row(Node("sqrt")), "sqrt", 3, 1, 1, "op"),
            (x_row, "square", 0, 2, 1, "fn"), (xy_row, "pow", 1, 2, 1, "fn"), ("(", "(", 2, 2, 1, "fn"), (")", ")", 3, 2, 1, "fn"),
            ("7", "7", 0, 3, 1, "num"), ("8", "8", 1, 3, 1, "num"), ("9", "9", 2, 3, 1, "num"), ("÷", "÷", 3, 3, 1, "op"),
            ("4", "4", 0, 4, 1, "num"), ("5", "5", 1, 4, 1, "num"), ("6", "6", 2, 4, 1, "num"), ("×", "×", 3, 4, 1, "op"),
            ("1", "1", 0, 5, 1, "num"), ("2", "2", 1, 5, 1, "num"), ("3", "3", 2, 5, 1, "num"), ("−", "−", 3, 5, 1, "op"),
            ("0", "0", 0, 6, 1, "num"), (".", ".", 1, 6, 1, "num"), ("%", "%", 2, 6, 1, "fn"), ("+", "+", 3, 6, 1, "op"),
            ("Ans", "ans", 0, 7, 1, "fn"), ("=", "eval", 1, 7, 3, "eq"),
        ]
        for row in (x_row, xy_row):
            for it in row.items:
                if isinstance(it, Node):
                    it.row = row
        self.buttons = [Button(label, action, cell(c, r, span), style) for label, action, c, r, span, style in layout]

    # ---------- math rendering ----------

    def font(self, size):
        if size not in self.fonts:
            self.fonts[size] = pygame.font.Font(self.serif_path, size)
        return self.fonts[size]

    def glyph(self, text, size, color):
        key = (text, size, color)
        if key not in self.glyphs:
            self.glyphs[key] = self.font(size).render(text, True, color)
        return self.glyphs[key]

    def measure(self, row, size, top=False):
        return self.render(row, size, None, 0, 0, IVORY_TEXT, top=top)

    def render(self, row, size, surf, x, base, color, carets=None, top=False):
        """Lay out (and, with a surface, draw) a Row. Returns (width, ascent, descent).

        `carets` collects (row, index, x, top, bottom) for every cursor position, which
        drives the cursor, horizontal scrolling and click-to-place.
        """
        asc, desc = round(size * 0.78), round(size * 0.26)
        dim = self.placeholder_color or GOLD_DIM
        x0 = x
        if not row.items:
            if carets is not None:
                carets.append((row, 0, x + (0 if top else 2), base - asc, base + desc))
            if top:
                return 0, asc, desc
            w, h = round(size * 0.52), round(size * 0.7)
            if surf:
                pygame.draw.rect(surf, dim, (x + 2, base - h, w - 4, h), max(1, round(size * 0.05)), border_radius=2)
            return w, asc, desc
        for i, it in enumerate(row.items):
            if carets is not None:
                carets.append((row, i, x, None, None))
            if isinstance(it, Node):
                w, a, d = self.render_node(it, size, surf, x, base, color, carets)
            else:
                text = it
                pad = round(size * 0.2) if it in BINOPS else 0
                g = self.glyph(text, size, color)
                if surf:
                    surf.blit(g, (x + pad, base - self.font(size).get_ascent()))
                w, a, d = g.get_width() + 2 * pad, asc, desc
            x += w
            asc, desc = max(asc, a), max(desc, d)
        if carets is not None:
            carets.append((row, len(row.items), x, None, None))
            # fill in this row's caret height now that its full extent is known
            for k in range(len(carets) - 1, -1, -1):
                r, i, cx, t, b = carets[k]
                if r is row and t is None:
                    carets[k] = (r, i, cx, base - asc, base + desc)
        return x - x0, asc, desc

    def render_node(self, node, size, surf, x, base, color, carets):
        s = self.s
        line_w = max(1, round(size * 0.055))
        if node.kind == "frac":
            sub = max(round(13 * s), round(size * 0.82))
            num, den = node.slots
            nw, na, nd = self.measure(num, sub)
            dw, da, dd = self.measure(den, sub)
            pad, margin = round(size * 0.12), round(size * 0.1)
            axis, gap = round(size * 0.3), max(2, round(size * 0.12))
            w = max(nw, dw) + 2 * pad
            num_base = base - axis - gap - nd
            den_base = base - axis + gap + da
            if surf:
                pygame.draw.line(surf, color, (x + margin, base - axis), (x + margin + w, base - axis), line_w)
            self.render(num, sub, surf, x + margin + (w - nw) / 2, num_base, color, carets)
            self.render(den, sub, surf, x + margin + (w - dw) / 2, den_base, color, carets)
            return w + 2 * margin, axis + gap + nd + na, den_base - base + dd
        if node.kind == "pow":
            sub = max(round(12 * s), round(size * 0.62))
            ew, ea, ed = self.measure(node.slots[0], sub)
            lift = round(size * 0.44)
            self.render(node.slots[0], sub, surf, x + 1, base - lift, color, carets)
            return ew + round(size * 0.06), lift + ea, max(0, ed - lift)
        # sqrt
        bw, ba, bd = self.measure(node.slots[0], size)
        hook, gap = round(size * 0.58), round(size * 0.1)
        top_y, bottom_y = base - ba - gap, base + bd
        self.render(node.slots[0], size, surf, x + hook, base, color, carets)
        w = hook + bw + round(size * 0.1)
        if surf:
            mid = base - ba * 0.32
            pts = [(x + size * 0.04, mid + size * 0.04), (x + hook * 0.28, mid - size * 0.04),
                   (x + hook * 0.55, bottom_y), (x + hook * 0.92, top_y), (x + w, top_y)]
            pygame.draw.lines(surf, color, False, pts, line_w)
        return w, ba + gap + line_w, bd + round(size * 0.06)

    # ---------- editing ----------

    def touch(self):
        self.last_input = time.time()
        try:
            self.preview = evaluate(self.expr, self.ans) if self.has_operator(self.expr) else None
        except (CalcError, ArithmeticError, ValueError, TypeError):
            self.preview = None

    @staticmethod
    def has_operator(row):
        return any(isinstance(it, Node) or it in BINOPS or it in "%()" or it == "Ans" for it in row.items)

    def start_fresh(self, keep_answer):
        """After =, the next key either continues from Ans (operators) or starts over."""
        self.result = None
        self.expr = Row()
        self.row, self.idx = self.expr, 0
        if keep_answer:
            self.insert("Ans")

    def insert(self, item):
        self.row.items.insert(self.idx, item)
        if isinstance(item, Node):
            item.row = self.row
        self.idx += 1

    def insert_node(self, kind, enter=True, fill=""):
        node = node_with(kind, fill)
        self.insert(node)
        if enter:
            self.row, self.idx = node.slots[0], 0

    def exit_node(self, node, after):
        self.row = node.row
        self.idx = node.row.items.index(node) + (1 if after else 0)

    def move_left(self):
        if self.idx > 0:
            it = self.row.items[self.idx - 1]
            if isinstance(it, Node):
                self.row = it.slots[-1]
                self.idx = len(self.row.items)
            else:
                self.idx -= 1
        elif self.row.parent:
            node, k = self.row.parent
            if k > 0:
                self.row = node.slots[k - 1]
                self.idx = len(self.row.items)
            else:
                self.exit_node(node, after=False)

    def move_right(self):
        if self.idx < len(self.row.items):
            it = self.row.items[self.idx]
            if isinstance(it, Node):
                self.row, self.idx = it.slots[0], 0
            else:
                self.idx += 1
        elif self.row.parent:
            node, k = self.row.parent
            if k < len(node.slots) - 1:
                self.row, self.idx = node.slots[k + 1], 0
            else:
                self.exit_node(node, after=True)

    def move_vertical(self, down):
        """Hop between numerator and denominator; outside a fraction, jump to line start/end."""
        r = self.row
        while r.parent:
            node, k = r.parent
            if node.kind == "frac" and k == (0 if down else 1):
                self.row = node.slots[1 if down else 0]
                self.idx = len(self.row.items)
                return
            r = node.row
        # next to a fraction on the line: step into it
        neighbour = self.row.items[self.idx] if self.idx < len(self.row.items) else None
        if neighbour is None and self.idx:
            neighbour = self.row.items[self.idx - 1]
        if isinstance(neighbour, Node) and neighbour.kind == "frac":
            self.row = neighbour.slots[1 if down else 0]
            self.idx = len(self.row.items)
            return
        self.idx = len(self.row.items) if down else 0

    def delete(self):
        if self.idx > 0:
            it = self.row.items[self.idx - 1]
            if isinstance(it, Node) and not it.empty():
                self.move_left()  # step inside and keep deleting from there
                return
            del self.row.items[self.idx - 1]
            self.idx -= 1
        elif self.row.parent:
            node, k = self.row.parent
            if node.empty():
                parent_row, pos = node.row, node.row.items.index(node)
                del parent_row.items[pos]
                self.row, self.idx = parent_row, pos
            elif k > 0:
                self.row = node.slots[k - 1]
                self.idx = len(self.row.items)
            else:
                self.exit_node(node, after=False)

    def clear(self):
        if self.expr.items or self.result:
            self.start_fresh(False)
        else:
            self.history.clear()
            self.history_scroll = 0

    def calculate(self):
        if not self.expr.items:
            return
        try:
            value, error = evaluate(self.expr, self.ans), None
            format_number(value)  # surfaces "too large" now rather than mid-draw
            self.ans = value
        except CalcError as e:
            value, error = None, str(e)
        self.history.append((clone_row(self.expr), value, error))
        self.history_scroll = 0
        self.result = (value, error)

    def act(self, action):
        if self.result is not None and action not in ("eval", "left", "right", "up", "down", "home", "end", "del", "clear", "copy"):
            continues = action in ("+", "−", "×", "÷", "%", "square", "pow") and self.result[1] is None
            self.start_fresh(keep_answer=continues)
        elif self.result is not None and action in ("left", "right", "up", "down", "home", "end", "del"):
            self.result = None  # go back to editing the expression
        if action in DIGITS or action in BINOPS or action in ("(", ")", "%"):
            self.insert(action)
        elif action == "ans":
            self.insert("Ans")
        elif action == "frac":
            self.insert_node("frac")
        elif action == "sqrt":
            self.insert_node("sqrt")
        elif action == "pow":
            self.insert_node("pow")
        elif action == "square":
            self.insert_node("pow", enter=False, fill="2")
        elif action == "left":
            self.move_left()
        elif action == "right":
            self.move_right()
        elif action in ("up", "down"):
            self.move_vertical(action == "down")
        elif action == "home":
            self.row, self.idx = self.expr, 0
        elif action == "end":
            self.row, self.idx = self.expr, len(self.expr.items)
        elif action == "del":
            self.delete()
        elif action == "clear":
            self.clear()
        elif action == "eval":
            if self.result is None:
                self.calculate()
        elif action == "copy":
            self.copy_result()
        self.touch()

    def copy_result(self):
        value = self.result[0] if self.result and self.result[0] is not None else self.ans
        try:
            text = format_number(value).replace(",", "")
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            pygame.scrap.put_text(text)
        except (pygame.error, CalcError, AttributeError):
            pass

    # ---------- drawing ----------

    def button_face(self, w, h, style, down, hover):
        key = (w, h, style, down, hover)
        if key not in self.face_cache:
            top, bottom, _ = STYLES[style]
            if down:
                top, bottom = [tuple(round(c * 0.78) for c in col) for col in (top, bottom)]
            elif hover:
                top = tuple(min(255, round(c * 1.12 + 6)) for c in top)
            face = vertical_gradient((w, h), top, bottom)
            if not down:
                pygame.draw.line(face, tuple(min(255, c + 34) for c in top), (6, 1), (w - 7, 1), 1)
            r = round(10 * self.s)
            face = rounded(face, r)
            pygame.draw.rect(face, GOLD_DIM if style != "eq" else (130, 104, 56), face.get_rect(), 1, border_radius=r)
            self.face_cache[key] = face
        return self.face_cache[key]

    def draw_buttons(self):
        mouse = pygame.mouse.get_pos()
        now = time.time()
        for b in self.buttons:
            down = self.pressed is b or now - self.flash.get(b.action, 0) < 0.09
            hover = b.rect.collidepoint(mouse)
            r = b.rect.move(0, 1 if down else 0)
            self.screen.blit(self.button_face(r.w, r.h, b.style, down, hover), r)
            color = STYLES[b.style][2]
            if isinstance(b.label, Row):
                size = round(20 * self.s)
                w, a, d = self.measure(b.label, size)
                self.placeholder_color = color
                self.render(b.label, size, self.screen, r.centerx - w / 2, r.centery + (a - d) / 2, color)
                self.placeholder_color = None
            else:
                f = self.f_caps_label() if b.label in ("DEL", "AC", "Ans") else (
                    self.f_op_label if b.label in BINOPS else self.f_label)
                g = f.render(b.label, True, color)
                self.screen.blit(g, g.get_rect(center=r.center))

    def f_caps_label(self):
        if not hasattr(self, "_caps_label"):
            self._caps_label = pygame.font.Font(self.serif_path, round(14 * self.s))
        return self._caps_label

    def draw_dial(self):
        scr, (cx, cy), R = self.screen, self.dial_center, self.dial_r
        r_in = R * 0.36
        pygame.draw.circle(scr, (8, 8, 10), (cx, cy + 2), R)  # drop shadow
        face = vertical_gradient((round(2 * R), round(2 * R)), (52, 49, 56), (20, 19, 23))
        mask = pygame.Surface(face.get_size(), pygame.SRCALPHA)
        pygame.draw.circle(mask, (255, 255, 255, 255), (R, R), R)
        face.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
        scr.blit(face, (cx - R, cy - R))
        now = time.time()
        for name, ang in (("right", 0), ("up", 90), ("left", 180), ("down", 270)):
            lit = self.dial_pressed == name or now - self.flash.get(name, 0) < 0.09
            if lit:
                pts = [(cx + rad * math.cos(math.radians(a)), cy - rad * math.sin(math.radians(a)))
                       for rad, rng in ((R - 2, range(ang - 44, ang + 45, 4)), (r_in, range(ang + 44, ang - 45, -4)))
                       for a in rng]
                pygame.draw.polygon(scr, (78, 66, 44), pts)
            mid = (R + r_in) / 2
            tip = (cx + (mid + R * 0.12) * math.cos(math.radians(ang)), cy - (mid + R * 0.12) * math.sin(math.radians(ang)))
            back = R * 0.14
            base_c = (cx + (mid - R * 0.06) * math.cos(math.radians(ang)), cy - (mid - R * 0.06) * math.sin(math.radians(ang)))
            perp = math.radians(ang + 90)
            tri = [tip, (base_c[0] + back * math.cos(perp), base_c[1] - back * math.sin(perp)),
                   (base_c[0] - back * math.cos(perp), base_c[1] + back * math.sin(perp))]
            pygame.draw.polygon(scr, GOLD if lit else GOLD_MUTED, tri)
        for a in (45, 135, 225, 315):  # seams between the four directions
            p0 = (cx + r_in * math.cos(math.radians(a)), cy - r_in * math.sin(math.radians(a)))
            p1 = (cx + (R - 3) * math.cos(math.radians(a)), cy - (R - 3) * math.sin(math.radians(a)))
            pygame.draw.line(scr, (10, 10, 12), p0, p1, 2)
        pygame.draw.circle(scr, GOLD_DIM, (cx, cy), R, 1)
        pygame.draw.circle(scr, (14, 14, 16), (cx, cy), r_in)
        pygame.draw.circle(scr, GOLD_MUTED, (cx, cy), r_in, max(1, round(1.5 * self.s)))
        pygame.draw.circle(scr, GOLD_DIM, (cx, cy), r_in * 0.45, 1)

    def draw_panel(self):
        s, scr, p = self.s, self.screen, self.panel
        pygame.draw.rect(scr, SCREEN_BG, p, border_radius=round(12 * s))
        pygame.draw.rect(scr, GOLD_DIM, p, 1, border_radius=round(12 * s))
        inner = p.inflate(-round(28 * s), -round(24 * s))
        size_main, size_hist = round(30 * s), round(19 * s)

        # bottom: result line
        result_h = round(44 * s)
        res_base = inner.bottom - round(10 * s)
        if self.result:
            value, error = self.result
            if error:
                g = self.font(round(22 * s)).render(error, True, ERROR)
                scr.blit(g, (inner.right - g.get_width(), res_base - self.font(round(22 * s)).get_ascent()))
            else:
                self.draw_value(value, round(34 * s), inner.right, res_base, GOLD, with_fraction=True)
        elif self.preview is not None:
            try:
                self.draw_value(self.preview, round(20 * s), inner.right, res_base, GOLD_MUTED, with_fraction=False)
            except CalcError:
                pass

        # expression line, scrolled sideways to keep the cursor in view
        w, asc, desc = self.measure(self.expr, size_main, top=True)
        expr_base = inner.bottom - result_h - desc
        carets = []
        self.render(self.expr, size_main, None, 0, 0, IVORY_TEXT, carets, top=True)
        cur = next((c for c in carets if c[0] is self.row and c[1] == self.idx), None)
        view = inner.w - round(6 * s)
        if cur:
            if cur[2] - self.scroll_x > view:
                self.scroll_x = cur[2] - view
            elif cur[2] - self.scroll_x < 0:
                self.scroll_x = cur[2]
        self.scroll_x = max(0, min(self.scroll_x, max(0, w - view)))
        scr.set_clip(inner)
        self.carets = []
        x0 = inner.left - self.scroll_x
        self.render(self.expr, size_main, scr, x0, expr_base, IVORY_TEXT, self.carets, top=True)
        blink_on = (time.time() - self.last_input) % 1.06 < 0.62
        cur = next((c for c in self.carets if c[0] is self.row and c[1] == self.idx), None)
        if cur and self.result is None and blink_on:
            _, _, cx, t, b = cur
            pygame.draw.line(scr, GOLD, (cx, t), (cx, b), max(2, round(2 * s)))
        if self.scroll_x > 0:
            g = self.glyph("…", size_hist, FAINT)
            scr.fill(SCREEN_BG, (inner.left, expr_base - asc, g.get_width() + 4, asc + desc))
            scr.blit(g, (inner.left, expr_base - self.font(size_hist).get_ascent()))

        # history above, newest at the bottom
        hist_bottom = expr_base - asc - round(14 * s)
        pygame.draw.line(scr, (34, 31, 28), (inner.left, hist_bottom + round(6 * s)), (inner.right, hist_bottom + round(6 * s)), 1)
        self.history_hits = []
        y = hist_bottom
        entries = self.history[: len(self.history) - self.history_scroll]
        for entry in reversed(entries):
            row, value, error = entry
            ew, ea, ed = self.measure(row, size_hist, top=True)
            line2 = round(size_hist * 1.25)
            top_y = y - line2 - ea - ed - round(6 * s)
            if y < inner.top:
                break
            res_base_h = y - round(4 * s)
            if error:
                g = self.font(size_hist).render(error, True, ERROR)
                scr.blit(g, (inner.right - g.get_width(), res_base_h - self.font(size_hist).get_ascent()))
            else:
                try:
                    self.draw_value(value, size_hist, inner.right, res_base_h, GOLD_MUTED, with_fraction=False)
                except CalcError:
                    pass
            self.render(row, size_hist, scr, inner.left, res_base_h - line2 - ed + round(4 * s), IVORY_MUTED, top=True)
            self.history_hits.append((pygame.Rect(inner.left, top_y, inner.w, y - top_y), entry))
            y = top_y - round(6 * s)
        scr.set_clip(None)

    def draw_value(self, value, size, right, base, color, with_fraction):
        text = "= " + format_number(value)
        g = self.font(size).render(text, True, color)
        x = right - g.get_width()
        self.screen.blit(g, (x, base - self.font(size).get_ascent()))
        frac = fraction_form(value) if with_fraction else None
        if frac:
            fsize = round(size * 0.62)
            w, a, d = self.measure(frac, fsize)
            self.render(frac, fsize, self.screen, x - w - round(18 * self.s), base - round(size * 0.12), GOLD_MUTED)

    def draw(self):
        s, scr = self.s, self.screen
        scr.blit(self.background, (0, 0))
        title = self.f_title.render("Minni", True, GOLD)
        scr.blit(self.f_title.render("Minni", True, (0, 0, 0)), (self.margin + 2, round(14 * s) + 2))
        scr.blit(title, (self.margin, round(14 * s)))
        caps = "  ".join("CALCULATOR")
        g = self.f_caps.render(caps, True, GOLD_MUTED)
        scr.blit(g, (self.width - self.margin - g.get_width(), round(14 * s) + title.get_height() - g.get_height() - round(6 * s)))
        self.draw_panel()
        self.draw_dial()
        self.draw_buttons()
        hint = self.f_hint.render("_ fraction  ·  ^ power  ·  r root  ·  Enter =  ·  Ctrl+C copy", True, FAINT)
        scr.blit(hint, hint.get_rect(midbottom=(self.width / 2, self.height - round(8 * s))))

    # ---------- input ----------

    def dial_at(self, pos):
        dx, dy = pos[0] - self.dial_center[0], self.dial_center[1] - pos[1]
        dist = math.hypot(dx, dy)
        if not self.dial_r * 0.36 <= dist <= self.dial_r:
            return None
        ang = math.degrees(math.atan2(dy, dx)) % 360
        return ["right", "up", "left", "down"][int(((ang + 45) % 360) // 90)]

    def click_expression(self, pos):
        if not self.panel.collidepoint(pos) or not self.carets:
            return False
        for rect, entry in self.history_hits:
            if rect.collidepoint(pos):  # recall a past calculation for editing
                self.result = None
                self.expr = clone_row(entry[0])
                self.row, self.idx = self.expr, len(self.expr.items)
                self.touch()
                return True
        best = min(self.carets, key=lambda c: abs(c[2] - pos[0]) + 0.6 * abs((c[3] + c[4]) / 2 - pos[1]))
        self.result = None
        self.row, self.idx = best[0], best[1]
        self.touch()
        return True

    KEY_ACTIONS = {
        pygame.K_BACKSPACE: "del", pygame.K_ESCAPE: "clear", pygame.K_DELETE: "clear",
        pygame.K_RETURN: "eval", pygame.K_KP_ENTER: "eval",
        pygame.K_LEFT: "left", pygame.K_RIGHT: "right", pygame.K_UP: "up", pygame.K_DOWN: "down",
        pygame.K_HOME: "home", pygame.K_END: "end",
    }
    CHAR_ACTIONS = {"-": "−", "*": "×", "x": "×", "X": "×", "/": "÷", "_": "frac", "^": "pow",
                    "r": "sqrt", "R": "sqrt", "a": "ans", "A": "ans", "=": "eval", "s": "square", ",": None}

    def handle(self, e):
        if e.type == pygame.QUIT:
            return False
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_c and e.mod & pygame.KMOD_CTRL:
                action = "copy"
            elif e.key in self.KEY_ACTIONS:
                action = self.KEY_ACTIONS[e.key]
            else:
                ch = e.unicode
                action = self.CHAR_ACTIONS.get(ch, ch if ch in DIGITS or ch in "+()%" else None)
            if action:
                self.flash[action] = time.time()
                self.act(action)
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.dial_pressed = self.dial_at(e.pos)
            if self.dial_pressed:
                self.act(self.dial_pressed)
                return True
            self.pressed = next((b for b in self.buttons if b.rect.collidepoint(e.pos)), None)
            if self.pressed:
                self.act(self.pressed.action)
            else:
                self.click_expression(e.pos)
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.pressed = self.dial_pressed = None
        elif e.type == pygame.MOUSEWHEEL:
            if self.panel.collidepoint(pygame.mouse.get_pos()):
                self.history_scroll = max(0, min(len(self.history) - 1, self.history_scroll - e.y))
        return True

    def run(self):
        running = True
        while running:
            busy = self.pressed or self.dial_pressed or any(time.time() - t < 0.1 for t in self.flash.values())
            first = pygame.event.wait(30 if busy else 120)  # short waits keep the cursor blinking
            for e in [first] + pygame.event.get():
                running = self.handle(e) and running
            self.draw()
            pygame.display.flip()
        pygame.quit()


if __name__ == "__main__":
    App().run()
