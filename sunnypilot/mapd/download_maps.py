#!/usr/bin/env python3
"""
CLI helper to download mapd offline OSM map tiles without terminal log flooding.
Usage:
  python3 download_maps.py CA
  python3 download_maps.py us_state.CA
  python3 download_maps.py --list
"""
import argparse
import io
import json
import math
import os
import sys
import tarfile
import urllib.request

BASE_URL = "https://map-data.pfeifer.dev"
GROUP_AREA_BOX_DEGREES = 2
DEFAULT_OSM_PATH = "/data/media/0/osm" if os.path.exists("/data/media/0") else os.path.expanduser("~/osm")

US_STATES = {
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

# Bounds for US states from download_menu.json
STATE_BOUNDS = {
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


def download_tiles(state_code: str, target_dir: str = DEFAULT_OSM_PATH):
  state_code = state_code.upper().replace("US_STATE.", "").replace("US.", "")
  if state_code not in STATE_BOUNDS:
    print(f"Error: Unknown state code '{state_code}'. Available: {', '.join(sorted(STATE_BOUNDS.keys()))}")
    sys.exit(1)

  min_lon, min_lat, max_lon, max_lat = STATE_BOUNDS[state_code]
  min_lat_a, min_lon_a, max_lat_a, max_lon_a = adjusted_bounds(min_lon, min_lat, max_lon, max_lat)

  tiles = []
  for lat in range(min_lat_a, max_lat_a, GROUP_AREA_BOX_DEGREES):
    for lon in range(min_lon_a, max_lon_a, GROUP_AREA_BOX_DEGREES):
      tiles.append((lat, lon))

  state_name = US_STATES.get(state_code, state_code)
  print(f"Downloading {len(tiles)} map tile packages for {state_name} ({state_code})...")
  print(f"Destination: {target_dir}")
  os.makedirs(target_dir, exist_ok=True)

  success_count = 0
  for idx, (lat, lon) in enumerate(tiles, start=1):
    rel_path = f"offline/{lat}/{lon}.tar.gz"
    url = f"{BASE_URL}/{rel_path}"
    print(f"[{idx}/{len(tiles)}] Downloading tile ({lat}, {lon})...", end="", flush=True)

    try:
      req = urllib.request.Request(url, headers={'User-Agent': 'BluePilot-MapDownloader'})
      with urllib.request.urlopen(req, timeout=30) as resp:
        if resp.status == 200:
          data = resp.read()
          with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            tar.extractall(path=target_dir)
          print(f" OK ({len(data) / 1024 / 1024:.1f} MB)")
          success_count += 1
        else:
          print(f" Skipped (HTTP {resp.status})")
    except urllib.error.HTTPError as e:
      if e.code == 404:
        print(" (empty tile / water)")
      else:
        print(f" Error (HTTP {e.code})")
    except Exception as e:
      print(f" Error: {e}")

  print(f"\nSuccessfully downloaded and extracted {success_count} tiles for {state_name}!")
  print("Map tiles are now ready for mapd.")


if __name__ == "__main__":
  parser = argparse.ArgumentParser(description="Download mapd offline maps")
  parser.add_argument("state", nargs="?", default="CA", help="State code (e.g. CA, NV, TX, WA)")
  parser.add_argument("--list", action="store_true", help="List available states")
  parser.add_argument("--dir", default=DEFAULT_OSM_PATH, help="Target OSM directory")
  args = parser.parse_args()

  if args.list:
    print("Available states:")
    for code, name in sorted(US_STATES.items()):
      if code in STATE_BOUNDS:
        print(f"  {code}: {name}")
    sys.exit(0)

  download_tiles(args.state, target_dir=args.dir)
