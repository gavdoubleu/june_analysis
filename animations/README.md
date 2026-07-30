# Making an animation

Turns a JUNE2 run into a map video. You edit one YAML, run one command.

## What you get

A **smoothed density heatmap** over a map background — not shaded region
polygons. One frame per time bin; colour = `rate_per_100k` by default (counts
and population are gridded separately, so crowded areas don't read hot
artificially — see [ADR-0007](../docs/adr/0007-density-heatmap-render-model.md)).

## 1. Install

Animation needs the core plus everything that draws:

```bash
pip install -r requirements.txt -r requirements-render.txt
```

Plus `world_reader`, which reads the World file and is **not on PyPI**. Install
editable from the MAY2 packaging shim:

```bash
pip install -e /path/to/MAY2/may_world_visualiser
```

## 2. You need two files

| File | What | Required |
|---|---|---|
| `simulation_events.h5` | the run's event log | yes |
| `world_state.h5` | geography + population | yes, for maps |

Events alone give curves and tables, never a map — the events file carries no
coordinates.

## 3. Copy a config and edit it

```bash
cp animations/configs/config_default.yaml animations/configs/config_mine.yaml
```

Edit these keys, nothing else to start:

```yaml
# Top-level scalars are interpolation anchors: any ${key} below resolves to them.
events_root: /path/to/your/run
world_root:  /path/to/your/world
output_root: /path/to/june_analysis/animations/output

inputs:
  events: ${events_root}/simulation_events.h5
  world:  ${world_root}/world_state.h5

aggregate:
  event_type:     infections   # required — never guessed
  days_per_frame: 1            # one frame per day — see "Timing" below

output:
  root:   ${output_root}
  name:   my_animation         # defaults to event_type
  format: mp4                  # or gif; or png = last frame only, as a preview
```

Absolute paths work fine without `${}`.

**Don't know your event types?** Leave `event_type:` blank and run — the error
lists every type in your run. Pick one and put it back.

## 4. Run it

```bash
python animations/animate_epidemic_example.py --config animations/configs/config_mine.yaml
```

Run from the repo root. Prints `wrote <path>` when done. Omit `--config` and it
uses `config_default.yaml`.

One file per run: to get mp4 *and* gif, flip `output.format` and run again.

## 5. Timing: `days_per_frame` and `fps`

**`days_per_frame` bins, it never skips.** Each frame shows the *sum* of every
event in its window — `days_per_frame: 7` gives one frame per week showing that
whole week's events, not "day 1, day 8, day 15". Bins are contiguous and cover
the run; no event is sampled away. Fractional values (`0.5`) work if the run's
time resolution supports them.

Two consequences:

- **Wider bins raise the colour scale.** More events per bin ⇒ a higher global
  maximum. A weekly render is not directly comparable with a daily one.
- **Playback speed = `days_per_frame ÷ fps` sim-days per second.** Defaults
  (1 and 2) give 2 sim-days/sec. Set `days_per_frame: 7` and the same `fps: 2`
  runs 7× faster, at 14 sim-days/sec.

`fps` is an integer, so to slow a weekly render you cannot drop below `fps: 1`.
Prefer keeping `days_per_frame: 1` and setting `fps` for the pace you want.

## 6. Attribution: which geo unit an event counts against

An event has two candidate **Geo unit**s — the *venue* it happened at, and the
*person*'s residence. Which you want depends on the metric, so the default
follows it:

| Metric | Default attribution | Why |
|---|---|---|
| `rate_per_100k` | `person` (residence) | denominator is *resident* population, so the numerator must count residents too |
| `count` | `venue`, then person | no denominator; "where transmission happened" is the signal |

**This matters.** Venue attribution puts a fair's visitors on its host unit: in
the 1348 medieval run, one 238-resident unit collected 28,520 infections — 119
per resident, a rate of 11,900,000 per 100k. Residence attribution caps the
ratio at 1.0, as it must.

Override either default explicitly — e.g. counts by residence:

```yaml
aggregate:
  event_type:   infections
  geo_priority: [person]     # or [venue, person], or a bare: person
```

## 7. Restyling (optional)

Everything cosmetic goes in an optional `render:` block. All keys optional; set
only what you want to change.

```yaml
render:
  ramp:  viridis
  fps:   15
  title: "Infections, 1348"
```

| Key | Default | Does |
|---|---|---|
| `metric` | `rate_per_100k` | scalar drawn; or `count` |
| `ramp` | `inferno` | matplotlib colour ramp (fiery black→red→orange→yellow) |
| `alpha_power` | `1.0` | `<1` fades in sooner, `>1` only opaque near max |
| `grid_resolution` | `1.0` | heatmap cells per km — raise for finer detail, slower |
| `sigma` | `2.0` | Gaussian smoothing, in grid cells |
| `projection` | auto | axis CRS name; default is the data's own UTM zone |
| `figure_height` | `8.0` | inches; width follows the bbox aspect |
| `fps` | `2` | frames per second — 2 simulated days/sec at `days_per_frame: 1` |
| `dpi` | `120` | resolution |
| `start_date` | none | ISO date, e.g. `1348-06-01`; labels frames with real dates |
| `title` | none | figure title |
| `basemap_style` | `shaded_relief` | `street`/`topo`/`imagery` add roads, towns, labels |
| `basemap_opacity` | `1.0` | `<1` mutes a busy basemap under the heatmap |
| `attribution` | style's own | override the credit line; `""` draws none |
| `background_image` | auto-fetch | path to your own basemap image |
| `require_basemap` | `false` | `true` = fail rather than render on blank |
| `cache_dir` | repo-local | where fetched basemap tiles cache |

Auto-detected, so never in config: bounding box, UTM zone, geo units, bin dates,
population.

## Troubleshooting

**`ModuleNotFoundError: world_reader`** — not installed. See step 1; it's an
editable install from MAY2, not pip-installable by name.

**Blank/white background** — the ESRI basemap fetch failed, usually no network.
The render carries on regardless. First fetch needs a connection; after that
tiles come from the cache. Set `require_basemap: true` to make failure loud.

**Muddy render on a detailed basemap** — `basemap_style: street`/`topo` are bright
and label-heavy, so a low `alpha_power` leaves the two fighting. Drop
`basemap_opacity` to ~0.5. Each style stamps its required credit bottom-right;
`attribution` replaces that line, `attribution: ""` removes it (do that only where
the surrounding document credits the source).

**Optional deps fail mid-render** — matplotlib/cartopy/ffmpeg are imported lazily,
so a missing one surfaces *after* the data loads, not at startup. Re-check step 1.
