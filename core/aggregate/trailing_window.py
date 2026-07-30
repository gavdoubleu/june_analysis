"""The *Trailing window* rewrite of an `Aggregate` (CONTEXT glossary).

Aggregate-to-Aggregate: each bin's value becomes the mean per bin over the
`window_days` ending at (and including) it, so a **Frame** reads a multi-day
average rather than one day's events. The *step* stays `days_per_bin`, so
consecutive bins overlap.

Deliberately *not* part of `aggregate_events` (which maps events to bins, a
different concept, on the numba fast path) and *not* part of the animator, whose
frames must keep reading strictly one bin each (ADR-0006/0007). Sitting above
both keeps that invariant intact and lets the epidemic curve reuse it.
"""

from __future__ import annotations

import numpy as np

from .aggregate import Aggregate


def trailing_mean(aggregate: Aggregate, window_days: float) -> Aggregate:
    """Rewrite `aggregate` so each bin holds the mean per bin over its window.

    Bins whose window is incomplete — the leading ``window_bins - 1`` — are
    dropped, with `bin_starts` truncated to match, rather than averaged over a
    smaller divisor (a different statistic, which would read as a spurious
    onset spike).
    """
    days_per_bin = aggregate.days_per_bin
    window_bins = int(round(window_days / days_per_bin))

    # Checked before the multiple test, whose "use 0 or 5" advice would be
    # nonsense here.
    if window_bins < 1:
        raise ValueError(
            f"window_days {window_days:g} is shorter than one bin "
            f"(days_per_frame {days_per_bin:g}); a window cannot be narrower "
            f"than the bins it averages"
        )

    # Reject rather than round: a 3.5-bin window rendered as 4 would put an
    # 8-day mean under a label claiming 7, and nobody re-reads warnings.
    if not np.isclose(window_bins * days_per_bin, window_days):
        shorter = np.floor(window_days / days_per_bin) * days_per_bin
        raise ValueError(
            f"window_days {window_days:g} is not a whole multiple of "
            f"days_per_frame {days_per_bin:g}; use {shorter:g} or "
            f"{shorter + days_per_bin:g}"
        )

    n_bins = aggregate.counts.shape[0]
    if window_bins > n_bins:
        raise ValueError(
            f"window_days {window_days:g} is longer than the whole aggregate "
            f"({n_bins} bin(s) of {days_per_bin:g} day(s)); every window would "
            f"be incomplete and no frame would survive"
        )

    # A one-bin window is the legal "off" setting: return the Aggregate as it
    # stands, integer counts and all, rather than a float copy claiming a
    # coverage wider than its step.
    if window_bins == 1:
        return aggregate

    # Cumulative sums give every window in one pass: the sum over the window
    # ending at bin i is cumulative[i + 1] - cumulative[i + 1 - window_bins].
    cumulative = np.cumsum(aggregate.counts, axis=0, dtype="float64")
    cumulative = np.vstack([np.zeros((1, aggregate.counts.shape[1])), cumulative])
    window_sums = cumulative[window_bins:] - cumulative[:-window_bins]

    return Aggregate(
        counts=window_sums / window_bins,
        geo_unit_ids=aggregate.geo_unit_ids,
        bin_starts=aggregate.bin_starts[window_bins - 1:],
        days_per_bin=aggregate.days_per_bin,
        event_type=aggregate.event_type,
        window_days=window_days,
    )
