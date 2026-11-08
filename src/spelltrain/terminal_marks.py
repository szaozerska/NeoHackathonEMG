"""Spacebar timing marks read from the terminal without waiting for Enter."""
from contextlib import contextmanager
import os
import select
import termios
import tty

SPACE = ord(' ')


@contextmanager
def keypress_mode(fd):
    """Deliver keys immediately; discard keys typed before entering and after leaving."""
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd, termios.TCSAFLUSH)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSAFLUSH, saved)


def space_presses_until(fd, deadline, clock, on_press):
    """Return the clock time of every space pressed before the deadline."""
    presses = []
    while (remaining := deadline-clock()) > 0:
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        pressed_at = clock()
        for key in os.read(fd, 64):
            if key == SPACE:
                presses.append(pressed_at); on_press(pressed_at)
    return presses
