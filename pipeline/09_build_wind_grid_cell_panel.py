"""Snap wind capacity to its nearest 0.25-degree ERA5/PECD grid cell.

Pure data processing script — no visualizations.

~/research/delu-headline-forecast is moving from zone-level (PEON/PEOF)
capacity weighting to grid-cell-level weighting, to remove the "capacity
spread uniformly within a zone" approximation zone-level weighting implies
(a zone can be ~50,000 km^2; turbines cluster along ridgelines/coasts, not
uniformly across that whole area — see that project's docs/data_sources.md
and docs/modeling_plan.md). This reuses
pipeline/07_build_wind_zone_panel.py's unit-to-grid-cell snapping
(`mpg.grid.nearest_grid_index`) but skips the zone-fraction-weighting step
that follows it there: each unit's full capacity is assigned to a single
nearest grid cell (no fractional split needed — unlike a zone, a grid cell
can't straddle another grid cell) and the monthly panel is grouped by
`(grid_lat, grid_lon)` instead of PEON/PEOF zone.

The grid itself (0.25 degree, full-Europe extent) is read from
`peon_mask_file`'s coordinate arrays purely for its geometry — every PECD
mask variable shares an identical grid (confirmed in
delu-headline-forecast's docs/data_sources.md), so no zone/mask *values*
are used here, just the lat/lon arrays. This is also the same grid
delu-headline-forecast pulls its own ERA5 subset on (see its
pipeline/19_download_era5_test_month.py), so a `(grid_lat, grid_lon)` here
lines up exactly with a cell there — no re-snapping needed on that side.

Output panels reuse the same monthly-snapshot machinery as
pipeline/03/07 (`mpg/panels.py`), just keyed by grid cell instead of
region/zone:
- `capacity_by_wind_onshore_grid_month_file`
- `capacity_by_wind_offshore_grid_month_file`
"""

import pandas as pd
import xarray as xr

from mpg.grid import nearest_grid_index
from mpg.panels import monthly_snapshot_panel
from mpg.paths import ProjPaths

paths = ProjPaths()
paths.ensure_directories()

EXPORT_START_PERIOD = pd.Period("2015-01", freq="M")


def snap_to_grid(units: pd.DataFrame, lats, lons) -> pd.DataFrame:
    units = units.copy()
    lat_idx = nearest_grid_index(units["latitude"].to_numpy(), lats)
    lon_idx = nearest_grid_index(units["longitude"].to_numpy(), lons)
    units["grid_lat"] = lats[lat_idx]
    units["grid_lon"] = lons[lon_idx]
    return units


def build_grid_month_panel(units: pd.DataFrame, series_name: str, month_range: pd.PeriodIndex) -> pd.DataFrame:
    panel = monthly_snapshot_panel(units, ["grid_lat", "grid_lon"], month_range, export_start_period=EXPORT_START_PERIOD)
    panel["series"] = series_name
    return panel


mask = xr.open_dataset(paths.peon_mask_file)
lats, lons = mask["latitude"].values, mask["longitude"].values
mask.close()

events = pd.read_parquet(
    paths.capacity_events_file,
    columns=[
        "unit_id", "technology", "region_code", "capacity_mw",
        "commissioning_date", "final_shutdown_date", "longitude", "latitude",
    ],
)
wind = events[events["technology"] == "wind"].copy()

has_coords = wind["longitude"].notna() & wind["latitude"].notna()
dropped_capacity_mw = wind.loc[~has_coords, "capacity_mw"].sum()
print(
    f"Wind units: {len(wind):,} total, {(~has_coords).sum():,} missing coordinates "
    f"({dropped_capacity_mw:,.1f} MW) dropped"
)
wind = wind[has_coords].copy()
wind = snap_to_grid(wind, lats, lons)

is_offshore = wind["region_code"].str.startswith("DEZZ")
onshore = wind[~is_offshore].copy()
offshore = wind[is_offshore].copy()

# Full history needed for the cumulative-sum in monthly_snapshot_panel to be
# correct; EXPORT_START_PERIOD trims the *output* to 2015 onward afterward —
# see pipeline/03_build_capacity_panel.py's module docstring ("Monthly export").
MONTH_RANGE = pd.period_range(
    start=wind["commissioning_date"].dt.to_period("M").min(),
    end=pd.Timestamp.today().to_period("M"),
    freq="M",
    name="period",
)

onshore_panel = build_grid_month_panel(onshore, "wind_onshore", MONTH_RANGE)
onshore_panel.to_parquet(paths.capacity_by_wind_onshore_grid_month_file, index=False)
print(
    f"Saved onshore grid-cell export: {len(onshore_panel):,} rows, "
    f"{onshore_panel[['grid_lat', 'grid_lon']].drop_duplicates().shape[0]} cells "
    f"-> {paths.capacity_by_wind_onshore_grid_month_file}"
)

offshore_panel = build_grid_month_panel(offshore, "wind_offshore", MONTH_RANGE)
offshore_panel.to_parquet(paths.capacity_by_wind_offshore_grid_month_file, index=False)
print(
    f"Saved offshore grid-cell export: {len(offshore_panel):,} rows, "
    f"{offshore_panel[['grid_lat', 'grid_lon']].drop_duplicates().shape[0]} cells "
    f"-> {paths.capacity_by_wind_offshore_grid_month_file}"
)
