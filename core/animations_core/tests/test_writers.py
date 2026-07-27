"""Tracer 7: the format registry.

The registry keys ``mp4`` / ``gif`` / ``png`` encoders (mirroring the projection
``@register`` idea); the format is guessed from the path extension when omitted.
End-to-end encoding of an :class:`~.writers.AnimationSource` (real gif + png) is
exercised through :class:`~.scene.Scene` in ``test_scene``; here we cover only
registration, format resolution and the Netscape-loop strip.
"""

import pytest

from core.animations_core.build_animation import writers


def test_register_holds_the_three_formats():
    assert set(writers.supported_formats()) >= {"mp4", "gif", "png"}


def test_resolve_format_guesses_extension_then_explicit_wins():
    assert writers.resolve_format("out/anim.gif", None) == "gif"
    assert writers.resolve_format("out/anim.mp4", None) == "mp4"
    # Explicit format overrides the extension.
    assert writers.resolve_format("out/anim.dat", "png") == "png"


def test_resolve_format_rejects_unknown():
    with pytest.raises(ValueError, match="format"):
        writers.resolve_format("out/anim.webm", None)


def test_set_gif_play_once_strips_netscape_loop_block():
    marker = b"\x21\xff\x0b" + b"NETSCAPE2.0"
    data = bytearray(b"GIF89a" + marker + b"\x03\x01\x00\x00\x00tail")
    stripped = writers._strip_netscape_loop(bytes(data))
    assert marker not in stripped
    assert stripped.endswith(b"tail")
