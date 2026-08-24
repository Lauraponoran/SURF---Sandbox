# Sandbox: manual-only, blank map

This branch (`sandbox/manual-only-blank`) is a clean copy of `main` for
feature experimentation. Changes from `main`:

- `trips.geojson` — emptied to `{"type":"FeatureCollection","features":[]}`
- `trips_metadata.json` — emptied to `{}`
- Everything else (app.js, index.html, config.js, filters, road quality
  layer, braking hotspots, leaderboard, styles, pipeline scripts) is
  unchanged.

The map loads fine with zero trips — the leaderboard, sensor legend, and
all filters just render empty until trips are added.

## Keeping this manual-only

`csv_to_geojson_converter.py` / `master_pipeline.py` only pull from the
Supabase API when run with the `--api` flag (`use_api` defaults to
`False`). To add trips here, drop CSVs in the input folder and run the
converter **without** `--api`:

```bash
python csv_to_geojson_converter.py
```

This regenerates `trips.geojson` / `trips_metadata.json` from local CSVs
only — no API-fetched trips will be mixed in. Just don't pass `--api` in
this branch and you're set.

Note: `config.js`'s `TRIPS_API_URL` isn't wired into the frontend at
runtime (it's a placeholder for a future live-fetch feature per its
comment) — it's the Python pipeline's `--api` flag that actually pulls
API trips, so avoiding that flag is what keeps this sandbox manual-only.
