"""Export a small, general-purpose wind + solar unit-level capacity extract,
plus cropped PECD PEON/PEOF region masks -- for downstream consumers that
want raw(ish) MaStR data without the ~12 GB bulk-dump setup cost, and
without this project pre-solving the region-assignment /
technology-classification / time-aggregation steps that are often the
actual point of working with this data (see e.g.
~/research/hackathon-power-system-planning, the first consumer of this
export, for a worked example of what a downstream project does with it).

Pure data processing -- no charts. Filters `capacity_events_file` (all
technologies, 8.9M rows) down to solar + wind, joins in solar's
`installation_type`/`usage_sector` (already present) and
`main_orientation`/`main_orientation_tilt_bucket` (from the separate
technical-detail table, via `unit_id`) -- together these are what's needed
to classify a solar unit into PECD's 4 technology codes (60/61/62/63:
industrial/residential rooftop, utility fixed/tracking) -- and
`pv_category` (feed-in/self-consumption behavior, a different axis, kept
for later behind-the-meter analysis, not needed for the classification
above). `unit_id` is dropped once the join is done: fully unique per row,
keeping it would roughly triple the output size for no benefit once its
only job (linking the two source tables) is complete.

Also crops the PEON/PEOF region masks (full-Europe rasters, ~85 MB each)
down to Germany's own zones and nonzero-weight grid cells only, converting
from a 2D raster into a long-format (zone_id, latitude, longitude, weight)
lookup table -- pure data-volume housekeeping, not a scientific
simplification (the mask's own per-cell weights are preserved exactly).

Deliberately does **not** do, on purpose -- downstream consumers are
expected to want to build at least some of this themselves:
- Assigning each wind unit to a PEON/PEOF zone (nearest 0.25-degree grid
  cell, then that cell's fractional zone weights from the mask below).
- Splitting "wind" into onshore/offshore (`region_code` starting with
  "DEZZ" is offshore -- see `pipeline/03_build_capacity_panel.py`).
- Mapping solar's `region_code` to its NUTS2 parent (first 4 characters).
- Classifying a solar unit into PECD's 4 technology codes (see
  `pipeline/24`-equivalent logic elsewhere, or work it out from
  `installation_type`/`usage_sector`/`main_orientation` yourself).
- Turning per-unit commissioning/shutdown dates into a monthly
  zone-capacity panel (contrast with `capacity_by_region_month_file`,
  which already does this -- this export is deliberately a step upstream
  of that).

See `book/markdown/wind_solar_export.md` for the full column reference,
worked examples of each step above, and known data-quality caveats.
"""

import pandas as pd
import xarray as xr

from mpg.paths import ProjPaths

RELEVANT_TECHNOLOGIES = ["solar", "wind"]
UNIT_COLUMNS = [
    "unit_id", "technology", "region_code", "capacity_mw",
    "commissioning_date", "final_shutdown_date", "longitude", "latitude",
    "installation_type", "usage_sector", "pv_category",
]
CATEGORICAL_COLUMNS = [
    "technology", "region_code", "installation_type", "usage_sector", "pv_category",
    "main_orientation", "main_orientation_tilt_bucket",
]

# Generous bounding box around Germany -- just to shrink the exported file,
# not for precision: zone assignment uses the mask's own per-cell weights,
# not this box.
LAT_RANGE = (56, 46)
LON_RANGE = (4, 16)


def _crop_region_mask(nc_path) -> pd.DataFrame:
    ds = xr.open_dataset(nc_path)
    de_zones = sorted(z for z in ds["region"].values.tolist() if str(z).startswith("DE"))
    mask = ds["mask"].sel(region=de_zones, latitude=slice(*LAT_RANGE), longitude=slice(*LON_RANGE))
    df = mask.to_dataframe(name="weight").reset_index()
    ds.close()
    return df[df["weight"] > 0].rename(columns={"region": "zone_id"}).reset_index(drop=True)


def main() -> None:
    paths = ProjPaths()
    paths.ensure_directories()

    events = pd.read_parquet(paths.capacity_events_file, columns=UNIT_COLUMNS)
    units = events[events["technology"].isin(RELEVANT_TECHNOLOGIES)].copy()

    detail = pd.read_parquet(
        paths.mastr_technical_detail_file("solar"),
        columns=["unit_id", "main_orientation", "main_orientation_tilt_bucket"],
    )
    n_before = len(units)
    units = units.merge(detail, on="unit_id", how="left")
    assert len(units) == n_before, "join must not change row count"

    units = units.drop(columns=["unit_id"])
    for col in CATEGORICAL_COLUMNS:
        units[col] = units[col].astype("category")

    units.to_parquet(paths.mastr_units_wind_solar_file, compression="zstd")
    print(
        f"Saved {len(units):,} units ({units['technology'].value_counts().to_dict()}) "
        f"-> {paths.mastr_units_wind_solar_file}"
    )

    peon_mask = _crop_region_mask(paths.peon_mask_file)
    peon_mask.to_parquet(paths.pecd_region_mask_peon_export_file)
    print(f"Saved PEON region mask: {len(peon_mask):,} nonzero (zone, cell) rows -> {paths.pecd_region_mask_peon_export_file}")

    peof_mask = _crop_region_mask(paths.peof_mask_file)
    peof_mask.to_parquet(paths.pecd_region_mask_peof_export_file)
    print(f"Saved PEOF region mask: {len(peof_mask):,} nonzero (zone, cell) rows -> {paths.pecd_region_mask_peof_export_file}")


if __name__ == "__main__":
    main()
