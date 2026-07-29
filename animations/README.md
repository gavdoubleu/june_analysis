# Making an animation

Turns a JUNE2 run into a map video. You edit one YAML, run one command.

## What you get

A **smoothed density heatmap** over a map background — not shaded region
polygons. One frame per time bin; colour = `rate_per_100k` by default (counts
and population are gridded separately, so crowded areas don't read hot
artificially — see [ADR-0007](../docs/adr/0007-density-heatmap-render-model.md)).

## 1. Install

Animation is the heaviest path — it needs core + plotting + maps + video:

```bash
pip install -r requirements.txt \
            -r requirements-plotting.txt \
            -r requirements-maps.txt \
            -r requirements-animation.txt
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
  days_per_frame: 1            # days per frame; raise for a shorter video

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

## 5. Restyling (optional)

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
| `ramp` | `magma` | matplotlib colour ramp |
| `alpha_power` | `1.0` | `<1` fades in sooner, `>1` only opaque near max |
| `grid_resolution` | `1.0` | heatmap cells per km — raise for finer detail, slower |
| `sigma` | `2.0` | Gaussian smoothing, in grid cells |
| `projection` | auto | axis CRS name; default is the data's own UTM zone |
| `figure_height` | `8.0` | inches; width follows the bbox aspect |
| `fps` | `10` | frames per second |
| `dpi` | `120` | resolution |
| `start_date` | none | ISO date, e.g. `1348-06-01`; labels frames with real dates |
| `title` | none | figure title |
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

**Optional deps fail mid-render** — matplotlib/cartopy/ffmpeg are imported lazily,
so a missing one surfaces *after* the data loads, not at startup. Re-check step 1.
