"""Nocturne: an 88-key concert grand you play from the computer keyboard or the mouse.

Sound comes from the Salamander Grand Piano samples (CC-BY 3.0, Alexander Holm); notes
between samples are pitch-shifted by at most one semitone.
"""
import ctypes
import os
import sys
from collections import Counter

import numpy as np
import pygame

HERE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
SAMPLE_DIR = os.path.join(HERE, "samples")
ICON_PATH = os.path.join(HERE, "icon.png")

RATE = 44100
LOW, HIGH = 21, 108          # A0 .. C8
MAX_SECONDS = 8              # tail kept per note; the decay is inaudible past this
RELEASE_MS = 280             # damper fall time when a key is let go
RETRIGGER_MS = 40
KEY_VELOCITY, ACCENT_VELOCITY = 0.8, 1.0

# Palette: black lacquer, ivory, burgundy felt, brushed gold
LACQUER_TOP, LACQUER_BOTTOM = (24, 22, 26), (7, 7, 9)
GOLD, GOLD_MUTED, GOLD_DIM = (206, 174, 102), (150, 128, 82), (78, 66, 44)
IVORY_TEXT, FAINT = (238, 232, 216), (122, 114, 100)
FELT_TOP, FELT_BOTTOM = (122, 24, 36), (78, 12, 22)
KEY_GAP = (26, 24, 22)

NOTE_NAMES = ["C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B"]
BLACK_PCS = {1, 3, 6, 8, 10}
SAMPLE_PCS = {"C": 0, "Ds": 3, "Fs": 6, "A": 9}  # sample file names, e.g. Ds4.mp3
# Real pianos set black keys off-centre: C♯/F♯ lean left, D♯/A♯ lean right.
BLACK_OFFSET = {1: -0.12, 3: 0.12, 6: -0.15, 8: 0.0, 10: 0.15}

# Tracker layout: bottom row = lower octave, top row = the octave above.
LOWER_ROW = "z s x d c v g b h n j m , l . ; /".split()
UPPER_ROW = "q 2 w 3 e r 5 t 6 y 7 u i 9 o 0 p [ = ]".split()
KEYMAP = {ord(c): i for i, c in enumerate(LOWER_ROW)}
KEYMAP.update({ord(c): 12 + i for i, c in enumerate(UPPER_ROW)})

CHORDS = {
    (0, 4, 7): "major", (0, 3, 7): "minor", (0, 3, 6): "diminished", (0, 4, 8): "augmented",
    (0, 5, 7): "sus4", (0, 2, 7): "sus2", (0, 4, 7, 10): "dominant seventh",
    (0, 4, 7, 11): "major seventh", (0, 3, 7, 10): "minor seventh",
    (0, 3, 6, 10): "half-diminished", (0, 3, 6, 9): "diminished seventh",
    (0, 4, 7, 9): "sixth", (0, 3, 7, 9): "minor sixth", (0, 3, 7, 11): "minor-major seventh",
}
INTERVALS = ["unison", "minor second", "major second", "minor third", "major third",
             "perfect fourth", "tritone", "perfect fifth", "minor sixth", "major sixth",
             "minor seventh", "major seventh"]


def note_name(midi):
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def describe(notes):
    """Name the chord or interval formed by the held notes, or '' if it has no common name."""
    pcs = sorted({n % 12 for n in notes})
    if len(notes) == 2 and len(pcs) == 2:
        lo, hi = sorted(notes)
        return INTERVALS[(hi - lo) % 12]
    for root in pcs:
        shape = tuple(sorted((p - root) % 12 for p in pcs))
        if shape in CHORDS:
            return f"{NOTE_NAMES[root]} {CHORDS[shape]}"
    return ""


class Piano:
    """Sample playback: one pre-built Sound per key, dampers, sustain pedal."""

    def __init__(self, progress):
        self.samples = {}
        files = sorted(f for f in os.listdir(SAMPLE_DIR) if f.endswith(".mp3"))
        for i, f in enumerate(files):
            name = f[:-4]
            pc = SAMPLE_PCS[name[:-1]]
            midi = (int(name[-1]) + 1) * 12 + pc
            raw = pygame.sndarray.array(pygame.mixer.Sound(os.path.join(SAMPLE_DIR, f)))
            self.samples[midi] = raw[: RATE * MAX_SECONDS].astype(np.float32)
            progress(0.4 * (i + 1) / len(files))
        self.sounds = {}
        for midi in range(LOW, HIGH + 1):
            self.sounds[midi] = self._build(midi)
            progress(0.4 + 0.6 * (midi - LOW + 1) / (HIGH - LOW + 1))
        self.active = {}        # midi -> (channel, sound)
        self.sustained = set()  # released while the pedal was down
        self.pedal = False
        self.volume = 0.8

    def _build(self, midi):
        src_midi = min(self.samples, key=lambda m: abs(m - midi))
        src = self.samples[src_midi]
        ratio = 2 ** ((midi - src_midi) / 12)
        if ratio != 1:
            pos = np.arange(int(len(src) / ratio)) * ratio
            grid = np.arange(len(src))
            src = np.stack([np.interp(pos, grid, src[:, c]) for c in range(2)], axis=1)
        loud = np.nonzero(np.abs(src).max(axis=1) > 24)[0]  # drop the silent tail
        out = src[: loud[-1] + 1 if len(loud) else len(src)].copy()
        fade = min(len(out), RATE // 20)
        out[-fade:] *= np.linspace(1, 0, fade)[:, None]
        return pygame.sndarray.make_sound(np.ascontiguousarray(out.clip(-32768, 32767).astype(np.int16)))

    def press(self, midi, velocity):
        if midi in self.active:
            self._damp(midi, RETRIGGER_MS)
        self.sustained.discard(midi)
        sound = self.sounds[midi]
        channel = sound.play()
        if channel:
            channel.set_volume(velocity * self.volume)
            self.active[midi] = (channel, sound)

    def release(self, midi):
        if midi not in self.active:
            return
        if self.pedal:
            self.sustained.add(midi)
        else:
            self._damp(midi, RELEASE_MS)

    def set_pedal(self, down):
        self.pedal = down
        if not down:
            for midi in list(self.sustained):
                self._damp(midi, RELEASE_MS)
            self.sustained.clear()

    def _damp(self, midi, ms):
        channel, sound = self.active.pop(midi)
        if channel.get_sound() is sound:  # the channel may already be reused by another note
            channel.fadeout(ms)


class Key:
    def __init__(self, midi, rect, black):
        self.midi, self.rect, self.black = midi, rect, black


def vertical_gradient(size, top, bottom):
    w, h = size
    surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        t = y / max(1, h - 1)
        pygame.draw.line(surf, [round(a + (b - a) * t) for a, b in zip(top, bottom)], (0, y), (w, y))
    return surf


def round_bottom(surf, radius):
    mask = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(),
                     border_bottom_left_radius=radius, border_bottom_right_radius=radius)
    surf.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    return surf


class App:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Hamzah.Nocturne.Piano")
        except (AttributeError, OSError):
            pass
        os.environ["SDL_VIDEO_CENTERED"] = "1"
        pygame.mixer.pre_init(RATE, -16, 2, 512, allowedchanges=0)
        pygame.init()
        pygame.mixer.set_num_channels(96)

        info = pygame.display.Info()
        base_w, base_h = 60 + 52 * 27, 118 + 12 + 158 + 16 + 46
        self.s = min(1.6, 0.92 * info.current_w / base_w, 0.8 * info.current_h / base_h)
        s = self.s
        self.margin = 30 * s
        self.white_w, self.white_h = 27 * s, round(158 * s)
        self.black_w, self.black_h = round(16 * s), round(100 * s)
        self.header_h, self.felt_h, self.rail_h = round(118 * s), round(12 * s), round(16 * s)
        self.keys_top = self.header_h + self.felt_h
        self.width = round(2 * self.margin + 52 * self.white_w)
        self.height = self.keys_top + self.white_h + self.rail_h + round(46 * s)

        self.screen = pygame.display.set_mode((self.width, self.height))
        pygame.display.set_caption("Nocturne — Concert Grand")
        if os.path.exists(ICON_PATH):
            pygame.display.set_icon(pygame.image.load(ICON_PATH))

        self.serif_path = pygame.font.match_font("palatinolinotype,georgia,timesnewroman")
        self.serif_italic_path = pygame.font.match_font("palatinolinotype,georgia,timesnewroman", italic=True)
        self.sans_path = pygame.font.match_font("segoeui,arial")
        self.f_title = self.font(self.serif_path, 42)
        self.f_notes = self.font(self.serif_path, 28)
        self.f_chord = self.font(self.serif_italic_path, 17)
        self.f_value = self.font(self.serif_path, 18)
        self.f_caps = self.font(self.serif_path, 10)
        self.f_label = self.font(self.sans_path, 10)
        self.f_hint = self.font(self.sans_path, 12)
        if None in self.f_notes.metrics("♯"):
            NOTE_NAMES[:] = [n.replace("♯", "#") for n in NOTE_NAMES]

        self.background = self.make_background()
        self.build_keys()
        self.key_cache = {}

        self.piano = Piano(self.splash)
        self.held = Counter()   # midi -> number of sources (keys, mouse) holding it
        self.key_holds = {}     # pygame key -> midi it started, so octave shifts never strand a note
        self.mouse_note = None
        self.octave = 3
        self.show_labels = True

    def font(self, path, size):
        return pygame.font.Font(path, max(8, round(size * self.s)))

    # ---------- static artwork ----------

    def make_background(self):
        bg = vertical_gradient((self.width, self.height), LACQUER_TOP, LACQUER_BOTTOM)
        sheen = vertical_gradient((self.width, self.header_h // 2), (255, 255, 255), (255, 255, 255))
        sheen.fill((255, 255, 255, 7), special_flags=pygame.BLEND_RGBA_MIN)
        bg.blit(sheen, (0, 0))
        return bg

    def build_keys(self):
        self.keys, whites = [], 0
        left = lambda i: round(self.margin + i * self.white_w)
        for midi in range(LOW, HIGH + 1):
            pc = midi % 12
            if pc in BLACK_PCS:
                cx = left(whites) + BLACK_OFFSET[pc] * self.black_w
                rect = pygame.Rect(round(cx - self.black_w / 2), self.keys_top, self.black_w, self.black_h)
                self.keys.append(Key(midi, rect, True))
            else:
                rect = pygame.Rect(left(whites), self.keys_top, left(whites + 1) - left(whites) - 1, self.white_h)
                self.keys.append(Key(midi, rect, False))
                whites += 1
        self.black_keys = [k for k in self.keys if k.black]
        self.white_keys = [k for k in self.keys if not k.black]

    def key_surface(self, w, h, black, down):
        cached = self.key_cache.get((w, black, down))
        if cached:
            return cached
        r = max(2, round(3 * self.s))
        if not black:
            lip = round((4 if down else 9) * self.s)
            top, bottom = ((236, 226, 202), (222, 210, 182)) if down else ((253, 251, 245), (236, 231, 218))
            surf = vertical_gradient((w, h), top, bottom)
            surf.blit(vertical_gradient((w, lip), (214, 206, 186), (190, 181, 160)), (0, h - lip))
            pygame.draw.line(surf, (255, 255, 255), (0, 0), (0, h - lip), 1)
            pygame.draw.line(surf, (200, 193, 176), (w - 1, 0), (w - 1, h), 1)
            if down:
                glow = vertical_gradient((w, round(h * 0.35)), GOLD, GOLD)
                glow.fill((255, 255, 255, 46), special_flags=pygame.BLEND_RGBA_MIN)
                surf.blit(glow, (0, 0))
        else:
            front = round((5 if down else 12) * self.s)
            inset = max(2, round(2.5 * self.s))
            surf = vertical_gradient((w, h), (34, 32, 38), (8, 8, 10))
            face_top, face_bottom = ((40, 37, 34), (18, 17, 18)) if down else ((66, 63, 70), (22, 21, 25))
            face = vertical_gradient((w - 2 * inset, h - front), face_top, face_bottom)
            surf.blit(face, (inset, 0))
            if down:
                pygame.draw.line(surf, GOLD_MUTED, (inset, 0), (w - inset - 1, 0), 1)
        surf = round_bottom(surf, r)
        self.key_cache[(w, black, down)] = surf
        return surf

    # ---------- text helpers ----------

    def spaced(self, font, text, color, spacing):
        glyphs = [font.render(ch, True, color) for ch in text]
        w = sum(g.get_width() for g in glyphs) + spacing * (len(glyphs) - 1)
        surf = pygame.Surface((max(1, w), font.get_height()), pygame.SRCALPHA)
        x = 0
        for g in glyphs:
            surf.blit(g, (x, 0))
            x += g.get_width() + spacing
        return surf

    def blit_center(self, surf, cx, y):
        self.screen.blit(surf, (round(cx - surf.get_width() / 2), round(y)))

    # ---------- drawing ----------

    def splash(self, fraction):
        pygame.event.pump()
        self.screen.blit(self.background, (0, 0))
        cx, cy = self.width / 2, self.height / 2
        self.blit_center(self.f_title.render("Nocturne", True, GOLD), cx, cy - 70 * self.s)
        self.blit_center(self.spaced(self.f_caps, "TUNING THE INSTRUMENT", GOLD_MUTED, round(4 * self.s)), cx, cy)
        bar_w, bar_h = 260 * self.s, max(2, round(2 * self.s))
        x, y = cx - bar_w / 2, cy + 28 * self.s
        pygame.draw.rect(self.screen, GOLD_DIM, (x, y, bar_w, bar_h))
        pygame.draw.rect(self.screen, GOLD, (x, y, bar_w * fraction, bar_h))
        pygame.display.flip()

    def labels(self):
        """Computer-key letters for each piano key at the current octave."""
        base, out = 12 * (self.octave + 1), {}
        for code, off in KEYMAP.items():
            out.setdefault(base + off, []).append(chr(code).upper())
        return out

    def draw(self):
        s, scr = self.s, self.screen
        scr.blit(self.background, (0, 0))
        self.draw_header()

        # keybed
        bed = pygame.Rect(round(self.margin) - 1, self.keys_top, self.width - 2 * round(self.margin) + 2, self.white_h)
        scr.fill(KEY_GAP, bed)
        labels = self.labels() if self.show_labels else {}
        for key in self.white_keys + self.black_keys:
            down = key.midi in self.held
            surf = self.key_surface(key.rect.w, key.rect.h, key.black, down)
            scr.blit(surf, key.rect)
            if key.midi in labels:
                color = GOLD if down else ((206, 196, 176) if key.black else (124, 114, 96))
                y = key.rect.bottom - round((20 if key.black else 22) * s)
                for text in reversed(labels[key.midi]):
                    glyph = self.f_label.render(text, True, color)
                    self.blit_center(glyph, key.rect.centerx, y)
                    y -= glyph.get_height() - round(2 * s)

        # the felt casts a soft shadow onto the keys
        shadow = vertical_gradient((bed.w, round(10 * s)), (0, 0, 0), (0, 0, 0))
        for y in range(shadow.get_height()):
            shadow.fill((0, 0, 0, round(110 * (1 - y / shadow.get_height()))), (0, y, bed.w, 1))
        scr.blit(shadow, (bed.x, self.keys_top))
        felt = vertical_gradient((bed.w, self.felt_h), FELT_TOP, FELT_BOTTOM)
        scr.blit(felt, (bed.x, self.header_h))

        # gold marker over the keys the computer keyboard currently reaches
        base = 12 * (self.octave + 1)
        reach = [k for k in self.keys if base <= k.midi <= base + 31]
        if reach:
            x0, x1 = reach[0].rect.left, reach[-1].rect.right
            pygame.draw.rect(scr, GOLD, (x0, self.keys_top - max(2, round(2 * s)), x1 - x0, max(2, round(2 * s))))

        # front rail
        rail_y = self.keys_top + self.white_h
        scr.blit(vertical_gradient((bed.w, self.rail_h), (30, 28, 32), (12, 12, 14)), (bed.x, rail_y))
        pygame.draw.line(scr, GOLD_DIM, (bed.x, rail_y), (bed.right, rail_y), 1)
        self.draw_footer(rail_y + self.rail_h)

    def draw_header(self):
        s, scr, m = self.s, self.screen, self.margin
        title = self.f_title.render("Nocturne", True, GOLD)
        scr.blit(self.f_title.render("Nocturne", True, (0, 0, 0)), (m + 2, 20 * s + 2))
        scr.blit(title, (m, 20 * s))
        scr.blit(self.spaced(self.f_caps, "CONCERT GRAND  ·  88 KEYS", GOLD_MUTED, round(4 * s)),
                 (m + 3 * s, 20 * s + title.get_height() + 2 * s))

        # centre: what is sounding
        notes = sorted(self.held)
        cx = self.width / 2
        if notes:
            text = "   ".join(note_name(n) for n in notes[:8]) + ("  …" if len(notes) > 8 else "")
            self.blit_center(self.f_notes.render(text, True, IVORY_TEXT), cx, 26 * s)
            chord = describe(notes)
            if chord:
                self.blit_center(self.f_chord.render(chord, True, GOLD), cx, 66 * s)
        else:
            self.blit_center(self.f_notes.render("—", True, FAINT), cx, 26 * s)

        # right: octave, volume, sustain
        col_w = 118 * s
        x = self.width - m - 3 * col_w
        caps = lambda t: self.spaced(self.f_caps, t, GOLD_MUTED, round(3 * s))
        base = 12 * (self.octave + 1)
        lo, hi = max(LOW, base), min(HIGH, base + 31)
        y_cap, y_val = 30 * s, 52 * s

        self.blit_center(caps("REACH"), x + col_w / 2, y_cap)
        self.blit_center(self.f_value.render(f"{note_name(lo)} – {note_name(hi)}", True, IVORY_TEXT), x + col_w / 2, y_val)

        x += col_w
        self.blit_center(caps("VOLUME"), x + col_w / 2, y_cap)
        seg_w, seg_gap, seg_h = round(6 * s), round(3 * s), round(14 * s)
        total = 10 * seg_w + 9 * seg_gap
        sx = x + col_w / 2 - total / 2
        lit = round(self.piano.volume * 10)
        for i in range(10):
            h = round(seg_h * (0.45 + 0.55 * i / 9))
            color = GOLD if i < lit else GOLD_DIM
            pygame.draw.rect(scr, color, (round(sx + i * (seg_w + seg_gap)), round(y_val + 18 * s - h), seg_w, h))

        x += col_w
        self.blit_center(caps("SUSTAIN"), x + col_w / 2, y_cap)
        on = self.piano.pedal
        r = round(6 * s)
        lamp = (round(x + col_w / 2), round(y_val + 11 * s))
        if on:
            for i, a in ((3, 30), (2, 60)):
                halo = pygame.Surface((r * 2 * i, r * 2 * i), pygame.SRCALPHA)
                pygame.draw.circle(halo, (*GOLD, a), (r * i, r * i), r * i)
                scr.blit(halo, (lamp[0] - r * i, lamp[1] - r * i))
        pygame.draw.circle(scr, GOLD if on else GOLD_DIM, lamp, r)

        y_rule = self.header_h - round(16 * s)
        pygame.draw.line(scr, GOLD_DIM, (m, y_rule), (self.width - m, y_rule), 1)

    def draw_footer(self, top):
        parts = [("Z – /", True), ("  &  ", False), ("Q – ]", True), ("  play      ", False),
                 ("← →", True), ("  octave      ", False), ("↑ ↓", True), ("  volume      ", False),
                 ("Space", True), ("  sustain      ", False), ("Shift", True), ("  accent      ", False),
                 ("Tab", True), ("  letters", False)]
        glyphs = [self.f_hint.render(t, True, IVORY_TEXT if k else FAINT) for t, k in parts]
        x = self.width / 2 - sum(g.get_width() for g in glyphs) / 2
        y = top + (self.height - top - glyphs[0].get_height()) / 2
        for g in glyphs:
            self.screen.blit(g, (round(x), round(y)))
            x += g.get_width()

    # ---------- input ----------

    def press(self, midi, velocity):
        if not LOW <= midi <= HIGH:
            return
        self.held[midi] += 1
        self.piano.press(midi, velocity)

    def release(self, midi):
        if midi not in self.held:
            return
        self.held[midi] -= 1
        if self.held[midi] <= 0:
            del self.held[midi]
            self.piano.release(midi)

    def release_all(self):
        for midi in list(self.held):
            self.held[midi] = 1
            self.release(midi)
        self.key_holds.clear()
        self.mouse_note = None
        self.piano.set_pedal(False)

    def key_at(self, pos):
        for key in self.black_keys + self.white_keys:
            if key.rect.collidepoint(pos):
                return key
        return None

    def mouse_velocity(self, key, y):
        depth = (y - key.rect.top) / key.rect.h  # deeper on the key = harder strike
        return 0.5 + 0.5 * min(1, max(0, depth))

    def mouse_to(self, pos):
        key = self.key_at(pos)
        midi = key.midi if key else None
        if midi == self.mouse_note:
            return
        if self.mouse_note is not None:
            self.release(self.mouse_note)
        self.mouse_note = midi
        if key:
            self.press(midi, self.mouse_velocity(key, pos[1]))

    def handle(self, e):
        if e.type == pygame.QUIT:
            return False
        if e.type == pygame.KEYDOWN:
            if e.key == pygame.K_ESCAPE:
                return False
            if e.key in KEYMAP and e.key not in self.key_holds:
                midi = 12 * (self.octave + 1) + KEYMAP[e.key]
                self.key_holds[e.key] = midi
                self.press(midi, ACCENT_VELOCITY if e.mod & pygame.KMOD_SHIFT else KEY_VELOCITY)
            elif e.key == pygame.K_SPACE:
                self.piano.set_pedal(True)
            elif e.key == pygame.K_LEFT:
                self.octave = max(0, self.octave - 1)
            elif e.key == pygame.K_RIGHT:
                self.octave = min(6, self.octave + 1)
            elif e.key == pygame.K_UP:
                self.piano.volume = min(1.0, round(self.piano.volume + 0.1, 1))
            elif e.key == pygame.K_DOWN:
                self.piano.volume = max(0.0, round(self.piano.volume - 0.1, 1))
            elif e.key == pygame.K_TAB:
                self.show_labels = not self.show_labels
        elif e.type == pygame.KEYUP:
            if e.key in self.key_holds:
                self.release(self.key_holds.pop(e.key))
            elif e.key == pygame.K_SPACE:
                self.piano.set_pedal(False)
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.mouse_to(e.pos)
        elif e.type == pygame.MOUSEMOTION and e.buttons[0]:
            self.mouse_to(e.pos)
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1 and self.mouse_note is not None:
            self.release(self.mouse_note)
            self.mouse_note = None
        elif e.type == pygame.WINDOWFOCUSLOST:
            self.release_all()
        return True

    def run(self):
        running = True
        self.draw()
        pygame.display.flip()
        while running:
            first = pygame.event.wait(250)  # wakes instantly on input, idles otherwise
            for e in [first] + pygame.event.get():
                running = self.handle(e) and running
            self.draw()
            pygame.display.flip()
        pygame.quit()


if __name__ == "__main__":
    App().run()
