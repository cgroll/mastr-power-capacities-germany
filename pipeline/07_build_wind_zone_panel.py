"""Fractionally assign wind capacity to PECD PEON/PEOF wind zones.

Pure data processing script — no visualizations.

PECD v4.2 offers no NUTS-level spatial aggregation for wind capacity factors
(unlike solar, which joins cleanly at NUTS2) — only two pan-European zone
schemes, PEON (onshore) and PEOF (offshore), each rasterized as a 0.25-degree
region mask (downloaded by `pipeline/06_download_pecd_masks.py`). See
`~/research/delu-headline-forecast/docs/data_sources.md` for the full PECD
background.

Each MaStR wind unit sits at a real (longitude, latitude) coordinate, which
usually lands in a raster cell with nonzero coverage from more than one zone
(e.g. a cell straddling two PEON zones might carry `DE01=0.86`, `DE02=0.14`).
Rather than assigning a unit's full capacity to a single "winning" zone
(argmax), this fractionally splits each unit's capacity across every zone
with nonzero weight at its cell, proportional to that weight — renormalized
across Germany's own zones for the relevant scheme, so a cell's residual
coverage by a neighboring country's zone doesn't leak German capacity out of
the German total (a German-registered unit's capacity belongs entirely to
Germany's own PEON/PEOF zones, whatever the raw raster split happens to look
like at that particular cell). The rare cell with zero coverage by any of the
scheme's German zones (only occurs right at the border) falls back to the
single nearest zone by (weighted) centroid distance instead.

Output panels reuse the same monthly-snapshot machinery as
`pipeline/03_build_capacity_panel.py` (`mpg/panels.py`), just keyed by
PEON/PEOF zone instead of NUTS3/NUTS2 region, and with each unit's
contribution pre-split across its candidate zones before the cumulative sum:
- `capacity_by_peon_month_file`: onshore wind, by PEON zone x month.
- `capacity_by_peof_month_file`: offshore wind, by PEOF zone x month.
"""

import numpy as np
import pandas as pd
import xarray as xr
from mpg.panels import monthly_snapshot_panel
from mpg.paths import ProjPaths

paths = ProjPaths()
paths.ensure_directories()

EXPORT_START_PERIOD = pd.Period("2015-01", freq="M")


def nearest_grid_index(values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Index of the nearest point in a regularly-spaced 1-D `grid` for each of `values`."""
    step = grid[1] - grid[0]
    idx = np.rint((values - grid[0]) / step).astype(int)
    return np.clip(idx, 0, len(grid) - 1)


def zone_centroids(mask_values: np.ndarray, lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mask-weighted (lat, lon) centroid per zone, for the zero-coverage-cell fallback."""
    lat_grid, lon_grid = np.meshgrid(lats, lons, indexing="ij")
    totals = mask_values.sum(axis=(1, 2))
    lat_c = (mask_values * lat_grid).sum(axis=(1, 2)) / totals
    lon_c = (mask_values * lon_grid).sum(axis=(1, 2)) / totals
    return lat_c, lon_c


def fractional_zone_weights(units: pd.DataFrame, mask_file, zone_prefix: str = "DE") -> pd.DataFrame:
    """One row per (unit_id, zone_id) with nonzero weight, weights summing to 1 per unit.

    `units` must have `unit_id`, `longitude`, `latitude` (rows with missing
    coordinates are the caller's responsibility to drop beforehand).
    """
    ds = xr.open_dataset(mask_file)
    zones = sorted(z for z in ds["region"].values.tolist() if str(z).startswith(zone_prefix))
    mask_values = ds["mask"].sel(region=zones).values  # (zone, lat, lon)
    lats, lons = ds["latitude"].values, ds["longitude"].values
    ds.close()

    lat_idx = nearest_grid_index(units["latitude"].to_numpy(), lats)
    lon_idx = nearest_grid_index(units["longitude"].to_numpy(), lons)
    weights = mask_values[:, lat_idx, lon_idx]  # (zone, n_units)
    totals = weights.sum(axis=0)

    zero_coverage = totals == 0
    if zero_coverage.any():
        centroid_lat, centroid_lon = zone_centroids(mask_values, lats, lons)
        unit_lat = units["latitude"].to_numpy()[zero_coverage]
        unit_lon = units["longitude"].to_numpy()[zero_coverage]
        dist2 = (unit_lat[:, None] - centroid_lat[None, :]) ** 2 + (unit_lon[:, None] - centroid_lon[None, :]) ** 2
        fallback_zone_idx = dist2.argmin(axis=1)
        weights = weights.copy()
        weights[:, zero_coverage] = 0.0
        weights[fallback_zone_idx, np.flatnonzero(zero_coverage)] = 1.0
        totals = weights.sum(axis=0)
        print(
            f"  {zero_coverage.sum()} unit(s) had zero '{zone_prefix}'-zone coverage at their nearest "
            f"grid cell in {mask_file.name}; assigned to the nearest zone by centroid instead"
        )

    normalized = weights / totals
    zone_idx_arr, unit_idx_arr = np.nonzero(normalized > 0)
    return pd.DataFrame(
        {
            "unit_id": units["unit_id"].to_numpy()[unit_idx_arr],
            "zone_id": np.array(zones)[zone_idx_arr],
            "weight": normalized[zone_idx_arr, unit_idx_arr],
        }
    )


def build_zone_month_panel(units: pd.DataFrame, mask_file, series_name: str, month_range: pd.PeriodIndex) -> pd.DataFrame:
    weights = fractional_zone_weights(units, mask_file)
    expanded = weights.merge(
        units[["unit_id", "capacity_mw", "commissioning_date", "final_shutdown_date"]], on="unit_id", how="left"
    )
    expanded["capacity_mw_weighted"] = expanded["capacity_mw"] * expanded["weight"]
    panel = monthly_snapshot_panel(
        expanded,
        ["zone_id"],
        month_range,
        export_start_period=EXPORT_START_PERIOD,
        capacity_col="capacity_mw_weighted",
        weight_col="weight",
    )
    panel = panel.rename(columns={"zone_id": "region_code"})
    panel["series"] = series_name
    return panel


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

peon_panel = build_zone_month_panel(onshore, paths.peon_mask_file, "wind_onshore", MONTH_RANGE)
peon_panel.to_parquet(paths.capacity_by_peon_month_file, index=False)
print(
    f"Saved monthly PEON export: {len(peon_panel):,} rows, {peon_panel['region_code'].nunique()} zones "
    f"-> {paths.capacity_by_peon_month_file}"
)

peof_panel = build_zone_month_panel(offshore, paths.peof_mask_file, "wind_offshore", MONTH_RANGE)
peof_panel.to_parquet(paths.capacity_by_peof_month_file, index=False)
print(
    f"Saved monthly PEOF export: {len(peof_panel):,} rows, {peof_panel['region_code'].nunique()} zones "
    f"-> {paths.capacity_by_peof_month_file}"
)
