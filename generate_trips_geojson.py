#!/usr/bin/env python3
"""
generate_trips_geojson.py

Builds trips.geojson from local processed trips only.

Loads every processed_sensor_data/*_processed.geojson file (wheel-rotation
speed, real road quality, braking detection — all computed by
integrated_processor.py) and merges them into a single trips.geojson.

Run: python generate_trips_geojson.py
"""

import json
import os
from pathlib import Path

OUTPUT_FILE    = "trips.geojson"
PROCESSED_ROOT = Path("processed_sensor_data")


def load_local_processed():
    """Load every processed_sensor_data/*_processed.geojson file."""
    features = []
    trip_ids = set()

    if not PROCESSED_ROOT.exists():
        print("ℹ️  No processed_sensor_data/ folder found — skipping local files")
        return features, trip_ids

    files = sorted(PROCESSED_ROOT.rglob("*_processed.geojson"))
    print(f"📂 Loading {len(files)} local processed file(s)…")

    for path in files:
        try:
            data = json.loads(path.read_text())
            for f in data.get("features", []):
                tid = f.get("properties", {}).get("trip_id")
                if tid:
                    trip_ids.add(tid)
                features.append(f)
        except Exception as e:
            print(f"  ⚠️  Could not read {path.name}: {e}")

    print(f"✅ Local: {len(features)} segments from {len(trip_ids)} trips")
    return features, trip_ids


def main():
    features, trip_ids = load_local_processed()

    geojson = {"type": "FeatureCollection", "features": features}
    with open(OUTPUT_FILE, "w") as f:
        json.dump(geojson, f, separators=(",", ":"))

    size_kb = os.path.getsize(OUTPUT_FILE) / 1024
    print(f"\n✅ Written {OUTPUT_FILE}")
    print(f"   Trips        : {len(trip_ids)}")
    print(f"   Total segments: {len(features)} ({size_kb:.0f} KB)")

    total_braking = sum(1 for f in features if f['properties'].get('is_braking'))
    print(f"   Total braking events: {total_braking}")


if __name__ == "__main__":
    main()
