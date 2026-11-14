"""Floppy drive sounds for the copier screen, made here (no recordings): the click of the head
stepping a cylinder, the rattle of a seek back to cylinder 0, and the hum of the motor.

Each is a short mono 16-bit WAV, written once to ~/.cache/turbocat/sounds; the window plays them
with Qt (QSoundEffect). Pure Python: a few thousand samples each.
"""
import math
import os
import random
import struct

from . import pictures

RATE = 22050
SOUND_DIR = os.path.join(pictures.CACHE, "sounds")
VERSION = 1                     # raise to make the sounds again after changing them here


def _wav(samples):
    data = b"".join(struct.pack("<h", max(-32767, min(32767, int(s * 32767)))) for s in samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, 1, RATE, RATE * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


def step():
    """One head step: a short, dull mechanical click (a decaying low thump plus a little noise)."""
    rnd = random.Random(1)
    n = int(RATE * 0.035)
    out = []
    for i in range(n):
        t = i / RATE
        env = math.exp(-t * 160)
        out.append(env * (0.55 * math.sin(2 * math.pi * 140 * t) + 0.25 * math.sin(2 * math.pi * 900 * t)
                          + 0.20 * (rnd.random() * 2 - 1)))
    return [s * 0.6 for s in out]


def seek(steps=20, every=0.012):
    """The head running back across many cylinders: quick clicks in a row ("brrrt")."""
    one = step()
    n = int(RATE * (steps * every + 0.04))
    out = [0.0] * n
    for k in range(steps):
        at = int(k * every * RATE)
        for i, s in enumerate(one):
            if at + i < n:
                out[at + i] += s * 0.7
    return out


def motor(seconds=1.0):
    """The spindle motor: a low hum with a slight wobble. Loops cleanly (whole cycles)."""
    n = int(RATE * seconds)
    out = []
    for i in range(n):
        t = i / RATE
        out.append(0.06 * math.sin(2 * math.pi * 50 * t) + 0.03 * math.sin(2 * math.pi * 100 * t)
                   + 0.015 * math.sin(2 * math.pi * 300 * t) * (1 + 0.3 * math.sin(2 * math.pi * 5 * t)))
    return out


SOUNDS = {"step": step, "seek": seek, "motor": motor}


def files():
    """{name: path of its WAV}, made the first time."""
    os.makedirs(SOUND_DIR, exist_ok=True)
    out = {}
    for name, make in SOUNDS.items():
        path = os.path.join(SOUND_DIR, f"{name}-{VERSION}.wav")
        if not os.path.exists(path):
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(_wav(make()))
            os.replace(tmp, path)
        out[name] = path
    return out
