"""Output-format registry — the animation's pure sink (ADR-0007).

Encoders are driven entirely by an :class:`AnimationSource` bundle (figure +
frame count + a ``draw`` callback + fps/dpi); they know nothing of ``Scene`` or
``Prepared``, so the dependency runs one way ``Scene -> writers -> ∅``. Each
concrete encoder registers under an extension via :func:`register` (mirroring the
projection ``@register`` idea); :func:`encode` resolves the format — explicit
argument, else guessed from the path extension — and dispatches:

- ``mp4`` -> ``FFMpegWriter`` (needs ffmpeg on the system PATH),
- ``gif`` -> ``PillowWriter``, then the Netscape loop block is stripped so the
  GIF plays once (matplotlib hardcodes infinite looping),
- ``png`` -> a single static frame (the final bin), for a still preview.

Frames stream via ``FuncAnimation`` — ``draw`` is called one index at a time and
each frame flushed to disk, never all materialised in memory. matplotlib /
Pillow are lazy-imported (ADR-0002), so the registry is defined without importing
any render dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

_WRITERS: dict[str, Callable[["AnimationSource", str], None]] = {}


@dataclass(frozen=True)
class AnimationSource:
    """The sink's input contract: everything an encoder needs, no ``Scene``.

    ``draw`` is a ``Callable[[int], None]`` (the bound ``Scene.draw_frame``) the
    encoder calls one frame at a time — frames are streamed to disk, never
    materialised in bulk. Heavy-dep-free, so it sits at module top (ADR-0002).
    """

    figure: Any
    frame_count: int
    draw: Callable[[int], None]
    fps: int
    dpi: int


def register(fmt: str) -> Callable[[Callable], Callable]:
    """Register the decorated function as the encoder for ``fmt``."""

    def decorator(func: Callable[[Any, str], None]) -> Callable[[Any, str], None]:
        _WRITERS[fmt] = func
        return func

    return decorator


def supported_formats() -> tuple[str, ...]:
    """The registered format names."""
    return tuple(_WRITERS)


def resolve_format(path: str, fmt: str | None) -> str:
    """The format to use: ``fmt`` if given, else the path extension.

    Raises ``ValueError`` for an unregistered format so an unsupported request
    fails loudly rather than writing an undecodable file.
    """
    from pathlib import Path

    resolved = (fmt or Path(path).suffix.lstrip(".")).lower()
    if resolved not in _WRITERS:
        raise ValueError(
            f"Unsupported output format {resolved!r}; "
            f"expected one of {sorted(_WRITERS)}."
        )
    return resolved


def encode(source: AnimationSource, path: str, fmt: str | None = None) -> None:
    """Encode ``source`` to ``path`` using the resolved encoder.

    The pure sink: driven entirely by the :class:`AnimationSource` bundle, with
    no reference back to ``Scene`` or ``Prepared``.
    """
    _WRITERS[resolve_format(path, fmt)](source, path)


def _build_animation(source: AnimationSource):
    """``FuncAnimation`` looping ``source.draw`` over ``source.frame_count``.

    Streams one frame at a time (``blit=False``); the writer flushes each to
    disk, so no frame array is held in memory.
    """
    from matplotlib.animation import FuncAnimation

    def update(index: int):
        source.draw(index)

    return FuncAnimation(
        source.figure, update, frames=source.frame_count, blit=False
    )


@register("mp4")
def _encode_mp4(source: AnimationSource, path: str) -> None:
    from matplotlib.animation import FFMpegWriter

    animation = _build_animation(source)
    try:
        animation.save(path, writer=FFMpegWriter(fps=source.fps), dpi=source.dpi)
    finally:
        _close(source.figure)


@register("gif")
def _encode_gif(source: AnimationSource, path: str) -> None:
    from matplotlib.animation import PillowWriter

    animation = _build_animation(source)
    try:
        animation.save(path, writer=PillowWriter(fps=source.fps), dpi=source.dpi)
    finally:
        _close(source.figure)
    _set_gif_play_once(path)


@register("png")
def _encode_png(source: AnimationSource, path: str) -> None:
    try:
        source.draw(source.frame_count - 1)
        source.figure.savefig(path, dpi=source.dpi)
    finally:
        _close(source.figure)


def _close(figure) -> None:
    import matplotlib.pyplot as plt

    plt.close(figure)


def _strip_netscape_loop(data: bytes) -> bytes:
    """Remove the 19-byte Netscape Application Block from GIF ``data``.

    Its absence makes viewers default to playing the GIF once. Borrowed from
    ``june_animator/src/map_utils.set_gif_play_once``.
    """
    marker = b"\x21\xff\x0b" + b"NETSCAPE2.0"
    buffer = bytearray(data)
    index = buffer.find(marker)
    if index != -1:
        del buffer[index : index + 19]
    return bytes(buffer)


def _set_gif_play_once(path: str) -> None:
    """Rewrite the GIF at ``path`` so it plays once instead of looping."""
    with open(path, "rb") as gif_file:
        data = gif_file.read()
    stripped = _strip_netscape_loop(data)
    if stripped != data:
        with open(path, "wb") as gif_file:
            gif_file.write(stripped)
