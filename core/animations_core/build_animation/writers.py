"""Output-format registry for the animation (ADR-0007).

A :class:`Prepared` is format-independent; the concrete encoders live here, each
registered under an extension via :func:`register` (mirroring the projection
``@register`` idea). :func:`write_animation` resolves the format — explicit
argument, else guessed from the path extension — and dispatches:

- ``mp4`` -> ``FFMpegWriter`` (needs ffmpeg on the system PATH),
- ``gif`` -> ``PillowWriter``, then the Netscape loop block is stripped so the
  GIF plays once (matplotlib hardcodes infinite looping),
- ``png`` -> a single static frame (the final bin), for a still preview.

Every encoder builds the layout + animation from the ``Prepared`` and closes the
figure afterwards. matplotlib / Pillow are lazy-imported (ADR-0002), so the
registry is defined without importing any render dependency.
"""

from __future__ import annotations

from typing import Any, Callable

_WRITERS: dict[str, Callable[[Any, str], None]] = {}


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


def write_animation(prepared: Any, path: str, fmt: str | None = None) -> None:
    """Encode ``prepared`` to ``path`` using the resolved writer."""
    _WRITERS[resolve_format(path, fmt)](prepared, path)


def _build_animation(prepared: Any):
    """``(scene, animation)`` looping :meth:`Prepared.draw_frame` over all bins."""
    from matplotlib.animation import FuncAnimation

    scene, mappable = prepared.build_layout()

    def update(index: int):
        prepared.draw_frame(scene, mappable, index)
        return (scene.heatmap_image, scene.date_text)

    animation = FuncAnimation(
        scene.figure,
        update,
        frames=len(prepared.smoothed_grids),
        blit=False,
    )
    return scene, animation


def _close(figure) -> None:
    import matplotlib.pyplot as plt

    plt.close(figure)


@register("mp4")
def _write_mp4(prepared: Any, path: str) -> None:
    from matplotlib.animation import FFMpegWriter

    scene, animation = _build_animation(prepared)
    try:
        animation.save(
            path,
            writer=FFMpegWriter(fps=prepared.config.fps),
            dpi=prepared.config.dpi,
        )
    finally:
        _close(scene.figure)


@register("gif")
def _write_gif(prepared: Any, path: str) -> None:
    from matplotlib.animation import PillowWriter

    scene, animation = _build_animation(prepared)
    try:
        animation.save(
            path,
            writer=PillowWriter(fps=prepared.config.fps),
            dpi=prepared.config.dpi,
        )
    finally:
        _close(scene.figure)
    _set_gif_play_once(path)


@register("png")
def _write_png(prepared: Any, path: str) -> None:
    scene, mappable = prepared.build_layout()
    try:
        prepared.draw_frame(scene, mappable, len(prepared.smoothed_grids) - 1)
        scene.figure.savefig(path, dpi=prepared.config.dpi)
    finally:
        _close(scene.figure)


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
