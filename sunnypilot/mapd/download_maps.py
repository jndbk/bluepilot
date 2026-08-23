#!/usr/bin/env python3
"""
CLI helper to download mapd offline OSM map tiles without terminal log flooding.
Usage:
  python3 download_maps.py US
  python3 download_maps.py CA
  python3 download_maps.py --list
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import io
import math
import os
import sys
import tarfile
import threading
import time
import urllib.request

BASE_URL = "https://map-data.pfeifer.dev"
GROUP_AREA_BOX_DEGREES = 2
DEFAULT_OSM_PATH = "/data/media/0/osm" if os.path.exists("/data/media/0") else os.path.expanduser("~/osm")

US_STATES = {
    "US": "Entire United States",
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}

# Bounding boxes (min_lon, min_lat, max_lon, max_lat)
STATE_BOUNDS = {
    "US": (-125.0, 24.5, -66.9, 49.5),
    "CA": (-124.41, 32.53, -114.13, 42.01),
    "NV": (-120.01, 35.00, -114.04, 42.00),
    "OR": (-124.57, 41.99, -116.46, 46.29),
    "WA": (-124.76, 45.54, -116.92, 49.00),
    "AZ": (-114.81, 31.33, -109.04, 37.00),
    "UT": (-114.05, 36.99, -109.04, 42.00),
    "TX": (-106.65, 25.84, -93.51, 36.50),
    "FL": (-87.63, 24.52, -80.03, 31.00),
    "NY": (-79.76, 40.50, -71.86, 45.02),
    "CO": (-109.06, 36.99, -102.04, 41.00),
    "NC": (-84.32, 33.84, -75.46, 36.59),
    "VA": (-83.67, 36.54, -75.24, 39.47),
    "GA": (-85.60, 30.36, -80.84, 35.00),
    "IL": (-91.51, 36.97, -87.49, 42.51),
    "OH": (-84.82, 38.40, -80.52, 42.33),
    "PA": (-80.52, 39.72, -74.69, 42.27),
}


def adjusted_bounds(min_lon, min_lat, max_lon, max_lat):
  min_lat_adj = int(math.floor(min_lat / GROUP_AREA_BOX_DEGREES)) * GROUP_AREA_BOX_DEGREES
  min_lon_adj = int(math.floor(min_lon / GROUP_AREA_BOX_DEGREES)) * GROUP_AREA_BOX_DEGREES
  max_lat_adj = int(math.floor(max_lat / GROUP_AREA_BOX_DEGREES)) * GROUP_AREA_BOX_DEGREES
  max_lon_adj = int(math.floor(max_lon / GROUP_AREA_BOX_DEGREES)) * GROUP_AREA_BOX_DEGREES

  if max_lat > max_lat_adj:
    max_lat_adj += GROUP_AREA_BOX_DEGREES
  if max_lon > max_lon_adj:
    max_lon_adj += GROUP_AREA_BOX_DEGREES

  return min_lat_adj, min_lon_adj, max_lat_adj, max_lon_adj


def fetch_tile(lat, lon, target_dir):
  rel_path = f"offline/{lat}/{lon}.tar.gz"
  url = f"{BASE_URL}/{rel_path}"
  try:
    req = urllib.request.Request(url, headers={'User-Agent': 'BluePilot-MapDownloader'})
    with urllib.request.urlopen(req, timeout=45) as resp:
      if resp.status == 200:
        data = resp.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
          tar.extractall(path=target_dir)
        return lat, lon, len(data), "OK"
  except urllib.error.HTTPError as e:
    if e.code == 404:
      return lat, lon, 0, "EMPTY"
    return lat, lon, 0, f"HTTP {e.code}"
  except Exception as e:
    return lat, lon, 0, str(e)
  return lat, lon, 0, "UNKNOWN"


def download_tiles(state_code: str, target_dir: str = DEFAULT_OSM_PATH, max_workers: int = 6):
  state_code = state_code.upper().replace("US_STATE.", "").replace("US.", "")
  if state_code not in STATE_BOUNDS:
    print(f"Error: Unknown region '{state_code}'. Available: {', '.join(sorted(STATE_BOUNDS.keys()))}")
    sys.exit(1)

  min_lon, min_lat, max_lon, max_lat = STATE_BOUNDS[state_code]
  min_lat_a, min_lon_a, max_lat_a, max_lon_a = adjusted_bounds(min_lon, min_lat, max_lon, max_lat)

  tiles = []
  for lat in range(min_lat_a, max_lat_a, GROUP_AREA_BOX_DEGREES):
    for lon in range(min_lon_a, max_lon_a, GROUP_AREA_BOX_DEGREES):
      tiles.append((lat, lon))

  state_name = US_STATES.get(state_code, state_code)
  print(f"==================================================")
  print(f"Downloading map tiles for {state_name} ({state_code})")
  print(f"Total grid cells: {len(tiles)} | Threads: {max_workers}")
  print(f"Destination: {target_dir}")
  print(f"==================================================")
  os.makedirs(target_dir, exist_ok=True)

  success_count = 0
  total_bytes = 0
  start_time = time.time()
  completed = 0
  lock = threading.Lock()

  with ThreadPoolExecutor(max_workers=max_workers) as executor:
    futures = {executor.submit(fetch_tile, lat, lon, target_dir): (lat, lon) for lat, lon in tiles}
    for future in as_completed(futures):
      lat, lon, size, status = future.result()
      with lock:
        completed += 1
        if status == "OK":
          success_count += 1
          total_bytes += size
          mb = size / 1024 / 1024
          print(f"[{completed:3d}/{len(tiles)}] ({lat:+3d}, {lon:+4d}) -> OK ({mb:4.1f} MB)")
        elif status == "EMPTY":
          # Ocean/unpopulated cell
          pass
        else:
          print(f"[{completed:3d}/{len(tiles)}] ({lat:+3d}, {lon:+4d}) -> {status}")

  elapsed = time.time() - start_time
  total_mb = total_bytes / 1024 / 1024
  print(f"\n==================================================")
  print(f"Complete! Downloaded {success_count} tile packages ({total_mb:.1f} MB) in {elapsed:.1f}s")
  print(f"Destination: {target_dir}/offline")
  print(f"==================================================")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Download mapd offline maps")
  parser.add_argument("state", nargs="?", default="US", help="State or region code (e.g. US, CA, NV, TX, WA)")
  parser.add_argument("--list", action="store_true", help="List available states")
  parser.add_argument("--dir", default=DEFAULT_OSM_PATH, help="Target OSM directory")
  parser.add_argument("-j", "--threads", type=int, default=6, help="Concurrent download threads")
  args = parser.parse_args()

  if args.list:
    print("Available regions:")
    for code, name in sorted(US_STATES.items()):
      if code in STATE_BOUNDS:
        print(f"  {code:4s}: {name}")
    sys.exit(0)

  download_tiles(args.state, target_dir=args.dir, max_workers=args.threads)
