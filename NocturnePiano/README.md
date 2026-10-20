# Nocturne

An 88-key concert grand piano for Windows. Play it with your computer keyboard or the mouse.
Real recorded piano samples, sustain pedal, chord names, and a black-lacquer-and-gold look.

## Controls

| Key | Does |
|---|---|
| `Z S X D C V G B H N J M , L . ; /` | Lower octave (white and black keys, like a piano) |
| `Q 2 W 3 E R 5 T 6 Y 7 U I 9 O 0 P [ = ]` | The octave above |
| `←` `→` | Move the keyboard reach down / up an octave |
| `↑` `↓` | Volume |
| `Space` (hold) | Sustain pedal |
| `Shift` + note | Accent (play louder) |
| `Tab` | Show / hide the key letters |
| Mouse | Click or drag across keys. Lower on the key = harder strike |
| `Esc` | Quit |

The thin gold line above the keys shows which keys your computer keyboard reaches right now.
The top bar shows the notes you hold and names the chord or interval.

## Run it

Double-click `dist\Nocturne.exe` (or the Desktop shortcut). From source:

```
pip install pygame numpy
python nocturne.py
```

## Build the exe

```
pip install pyinstaller pillow
python make_icon.py
pyinstaller --noconfirm --onefile --windowed --name Nocturne --icon icon.ico --add-data "samples;samples" --add-data "icon.png;." nocturne.py
```

The exe lands in `dist\`. PyInstaller binaries sometimes trigger antivirus false positives;
build it yourself from this source if in doubt.

## Files

- `nocturne.py`: the app
- `samples/`: piano samples (one every minor third; the notes in between are pitch-shifted by one semitone at most)
- `fetch_samples.py`: re-downloads the samples
- `make_icon.py`: draws `icon.png` / `icon.ico`

## Credits

Piano samples: [Salamander Grand Piano](https://archive.org/details/SalamanderGrandPianoV3) by Alexander Holm,
licensed [CC-BY 3.0](https://creativecommons.org/licenses/by/3.0/), via the MP3 set hosted by
[Tone.js](https://github.com/Tonejs/audio).

No warranty. Use at your own risk.
