"""Download the Salamander Grand Piano samples (CC-BY 3.0, Alexander Holm) used by Nocturne.

The tone.js project hosts a trimmed MP3 set with one sample every minor third
(A, C, D#, F# in each octave); Nocturne pitch-shifts the gaps by at most one semitone.
"""
import pathlib
import urllib.request

BASE = "https://tonejs.github.io/audio/salamander/"
OUT = pathlib.Path(__file__).parent / "samples"


def names():
    yield "A0"
    for octave in range(1, 8):
        for pc in ("C", "Ds", "Fs", "A"):
            yield f"{pc}{octave}"
    yield "C8"


def main():
    OUT.mkdir(exist_ok=True)
    for name in names():
        dest = OUT / f"{name}.mp3"
        if dest.exists():
            continue
        urllib.request.urlretrieve(BASE + dest.name, dest)
        print("fetched", dest.name)


if __name__ == "__main__":
    main()
