import csv
import json
import os
import re
import sys
from datetime import datetime

INPUT_ROOT = "csv_data"       # where CSVs live
OUTPUT_ROOT = "sensor_data"   # where cleaned GeoJSONs + metadata go

# Speed spike filtering
MAX_BIKE_SPEED_KMH = 60       # hard cap — anything above this is physically implausible
MAX_NEIGHBOUR_RATIO = 2.5     # a point is a spike if it's >2.5x both its neighbours


# ─────────────────────────────────────────────────────────────────────────────
# Speed spike filtering (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def filter_gnss_max_speed(gnss_value):
    """
    Parse the raw GNSS CSV line, replace MAX km/h with a spike-filtered value,
    and return the sanitised string.
    """
    parts = gnss_value.split(',')
    if len(parts) < 7:
        return gnss_value

    try:
        raw_max = float(parts[6])
    except (ValueError, TypeError):
        return gnss_value

    filtered_max = min(raw_max, MAX_BIKE_SPEED_KMH)

    try:
        avg_speed = float(parts[4])
        if avg_speed > 0 and filtered_max > avg_speed * MAX_NEIGHBOUR_RATIO:
            filtered_max = round(avg_speed * MAX_NEIGHBOUR_RATIO, 1)
    except (ValueError, TypeError):
        pass

    if filtered_max != raw_max:
        print(f"    ⚡ GPS spike filtered: {raw_max} km/h → {filtered_max} km/h")

    parts[6] = str(filtered_max)
    return ','.join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Per-row timestamp extraction
# ─────────────────────────────────────────────────────────────────────────────

# Known/likely column names, matched case-insensitively. Local hardware CSVs
# aren't guaranteed to use the same header, so we fall back to any column
# whose name simply *contains* "timestamp", or common date-only variants.
# If a device CSV turns out to use something else entirely, add its exact
# header here.
_TIMESTAMP_KEY_CANDIDATES = ('gnss timestamp', 'timestamp', 'datetime', 'date time', 'date')

_TIMESTAMP_FORMATS = (
    '%Y-%m-%d %H:%M:%S.%f',
    '%Y-%m-%d %H:%M:%S',
    '%Y-%m-%dT%H:%M:%S.%f',
    '%Y-%m-%dT%H:%M:%S',
)

def extract_row_timestamp(row):
    """
    Find a per-row timestamp/date value in a CSV DictReader row and return it
    as an ISO-8601 string when it matches a known format, or the raw string
    as-is if not (still useful for display/filtering even if unparsed).
    Returns None if no timestamp-like column is present or the value is empty.
    """
    for key, val in row.items():
        if not val:
            continue
        key_lower = (key or '').strip().lower()
        if key_lower in _TIMESTAMP_KEY_CANDIDATES or 'timestamp' in key_lower:
            val = val.strip()
            if not val:
                continue
            for fmt in _TIMESTAMP_FORMATS:
                try:
                    return datetime.strptime(val, fmt).isoformat()
                except ValueError:
                    continue
            return val  # unparsed but non-empty — pass through raw
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Trip numbering
# ─────────────────────────────────────────────────────────────────────────────

def get_next_trip_number(sensor_id_folder):
    """Find the next available trip number inside a sensor_data/{sensor_id} folder."""
    if not os.path.exists(sensor_id_folder):
        return 1
    existing = [
        int(m.group(1))
        for f in os.listdir(sensor_id_folder)
        if (m := re.match(r".*_Trip(\d+)_clean\.geojson", f))
    ]
    return max(existing, default=0) + 1


# ─────────────────────────────────────────────────────────────────────────────
# CSV → GeoJSON
# ─────────────────────────────────────────────────────────────────────────────

def process_csv(input_path, sensor_id, trip_num):
    """Convert a local CSV file to GeoJSON features + metadata dict."""
    features = []
    coords = []
    last_lat, last_lon = None, None

    with open(input_path, newline='') as csvfile:
        reader = list(csv.DictReader(csvfile))

        for row in reader:
            lat, lon = row.get('latitude'), row.get('longitude')
            try:
                lat_f, lon_f = float(lat), float(lon)
                last_lat, last_lon = lat_f, lon_f
                coords.append((lat_f, lon_f))
            except (ValueError, TypeError):
                coords.append((last_lat, last_lon) if last_lat and last_lon else None)

        for i in range(len(reader) - 1):
            row1, row2 = reader[i], reader[i + 1]
            coord1, coord2 = coords[i], coords[i + 1]
            if coord1 and coord2:
                props = {k: v for k, v in row1.items() if k not in ['latitude', 'longitude']}
                props["trip_id"] = f"{sensor_id}_Trip{trip_num}"
                row_ts = extract_row_timestamp(row1)
                if row_ts:
                    props["timestamp"] = row_ts
                feature = {
                    "type": "Feature",
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [
                            [coord1[1], coord1[0]],
                            [coord2[1], coord2[0]]
                        ]
                    },
                    "properties": props
                }
                features.append(feature)

    metadata = {}

    with open(input_path, "r") as f:
        lines = f.readlines()

    last_gps_line = 0
    for i, line in enumerate(lines):
        parts = line.strip().split(',')
        if len(parts) >= 2:
            try:
                float(parts[0]); float(parts[1])
                last_gps_line = i
            except ValueError:
                continue

    for line in lines[last_gps_line + 1:]:
        line = line.strip()
        if not line:
            continue
        if line.startswith(','):
            continue
        if ':' in line:
            key, val = line.split(':', 1)
            key = key.strip()
            if key and not key[0].isdigit():
                metadata[key] = val.strip()
        elif line == "BLE Device Information Service":
            metadata[line] = line
        elif line.startswith('SENSOR,') or line.startswith('GNSS,'):
            parts = line.split(',', 1)
            if len(parts) == 2:
                raw_value = ',' + parts[1]
                if parts[0] == 'GNSS':
                    raw_value = filter_gnss_max_speed(raw_value)
                metadata[parts[0]] = raw_value

    metadata["source"] = "local_csv"

    # Derive a trip-level date range from the per-row timestamps we just
    # extracted.
    row_timestamps = [f["properties"].get("timestamp") for f in features if f["properties"].get("timestamp")]
    if row_timestamps and "Trip start/end" not in metadata:
        metadata["Trip start/end"] = f", {row_timestamps[0]}, {row_timestamps[-1]}"

    return features, metadata


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_ROOT, exist_ok=True)
    os.makedirs(INPUT_ROOT, exist_ok=True)

    metadata_index_file = "trips_metadata.json"
    if os.path.exists(metadata_index_file):
        with open(metadata_index_file, "r", encoding="utf-8") as f:
            all_metadata = json.load(f)
    else:
        all_metadata = {}

    # ── Process all CSVs in csv_data/ ────────────────────────────────────────
    processed_any = False

    for entry in os.listdir(INPUT_ROOT):
        entry_path = os.path.join(INPUT_ROOT, entry)

        if os.path.isdir(entry_path):
            csv_files = [os.path.join(entry_path, f)
                         for f in os.listdir(entry_path) if f.lower().endswith(".csv")]
        elif entry.lower().endswith(".csv"):
            csv_files = [entry_path]
        else:
            continue

        for input_file in csv_files:
            file = os.path.basename(input_file)
            sensor_id = file.split("_")[0][-5:]

            # ── Deduplication ─────────────────────────────────────────────────
            already = any(
                v.get("source_file") == file
                for v in all_metadata.values()
            )
            if already:
                print(f"⏭️  {file} already in metadata — skipping.")
                continue

            # ── Assign trip number ────────────────────────────────────────────
            sensor_output = os.path.join(OUTPUT_ROOT, sensor_id)
            os.makedirs(sensor_output, exist_ok=True)
            trip_num = get_next_trip_number(sensor_output)
            trip_id  = f"{sensor_id}_Trip{trip_num}"

            features, metadata = process_csv(input_file, sensor_id, trip_num)

            geojson = {"type": "FeatureCollection", "features": features}
            out_geojson = os.path.join(sensor_output, f"{trip_id}_clean.geojson")
            with open(out_geojson, "w", encoding="utf-8") as f:
                json.dump(geojson, f, indent=2)

            trip_metadata = {"source_file": file}
            trip_metadata.update(metadata)
            all_metadata[trip_id] = trip_metadata

            with open(metadata_index_file, "w", encoding="utf-8") as f:
                json.dump(all_metadata, f, indent=2)

            print(f"✅ 📄 CSV {file} → {trip_id}_clean.geojson in {sensor_output}")
            processed_any = True

    if not processed_any:
        print("ℹ️  Nothing new to process.")


if __name__ == "__main__":
    main()
