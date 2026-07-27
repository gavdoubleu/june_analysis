"""A ``june_analysis``-owned facade above the vendored ``june_events`` reader.

``SimulationEvents`` is a bound handle to one run's *Events file*: it owns the
``events/`` HDF5 prefix and the ``str(path)`` coercion that Consumers otherwise
hand-roll on every call, and caches the single ``inspect_file`` scan its methods
share. Events-only by design — the World file is an input the run *consumes*, not
something it produced, so it stays out of this seam (ADR-0003).
"""

from dataclasses import dataclass

from .june_events import inspect_file, load_decoded_events, load_enriched_events

_EVENTS_PREFIX = "events/"


@dataclass(frozen=True)
class EventTypeSummary:
    """One available event type: its ``name`` (``events/`` prefix stripped) and the
    number of rows recorded for it. ``n_rows`` may be 0 — an empty-but-present type;
    a Consumer decides whether to skip it."""

    name: str
    n_rows: int


class SimulationEvents:
    """Reader handle to one run's Events file, bound to ``events_path`` once."""

    def __init__(self, events_path):
        self._path = str(events_path)  # accept str | Path; coerce once, here
        self._summary = None  # lazy FileSummary cache, shared by every method

    def _scan(self):
        if self._summary is None:
            self._summary = inspect_file(self._path)
        return self._summary

    def event_types(self) -> list[EventTypeSummary]:
        """Every ``events/`` dataset in the file, empties included, sorted by name."""
        summary = self._scan()
        types = [
            EventTypeSummary(
                name=dataset.path[len(_EVENTS_PREFIX):], n_rows=dataset.n_rows
            )
            for dataset in summary.datasets
            if dataset.path.startswith(_EVENTS_PREFIX)
        ]
        return sorted(types, key=lambda event_type: event_type.name)

    def _dataset_path(self, event_type: str) -> str:
        # Own the events/ prefix; the facade knows the valid set, so name an absent
        # type explicitly (KeyError listing what is available) rather than let the
        # low-level load return None. An empty-but-present type is NOT absent.
        available = [event.name for event in self.event_types()]
        if event_type not in available:
            raise KeyError(
                f"unknown event type {event_type!r}; available: {available}"
            )
        return f"{_EVENTS_PREFIX}{event_type}"

    def events(self, event_type: str, columns=None):
        """Light path — the *Decoded event table* for ``event_type``."""
        return load_decoded_events(
            self._path, self._dataset_path(event_type), columns=columns
        )

    def enriched(self, event_type: str, with_people: bool = True, with_venues: bool = True):
        """Heavy path — the *Enriched event table* (people/venue joins) for
        ``event_type``. Join toggles forward to ``load_enriched_events``."""
        return load_enriched_events(
            self._path,
            self._dataset_path(event_type),
            with_people=with_people,
            with_venues=with_venues,
        )
