"""Assign each MaStR unit to a region and build the annual capacity panel.

Pure data processing script — no visualizations.

Outputs:
- `capacity_events_file`: unit-level table with a `region_code` assigned
  (NUTS3 for onshore units, a synthetic offshore code for offshore wind),
  ready for time-slicing.
- `capacity_by_region_year_file`: the annual snapshot panel used for the EDA
  and later maps/time series — one row per (region, technology, year) with
  total installed capacity and unit count as of Dec 31 of that year.
- `capacity_by_region_year_pv_category_file`: same idea, but solar-only and
  split by behind-the-meter category instead of technology (see below).
- `capacity_by_region_month_file` / `capacity_by_offshore_month_file`: monthly
  (end-of-month) exports from 2015 on, for combining with weather data at
  region/month granularity — see "Monthly export" below.
- `offshore_regions_file`: offshore wind footprint polygons (see "Offshore
  region polygons" below).

Historic snapshots use *fixed, current* NUTS3 boundaries: only the installed
capacity changes across years, not the region geometry. Reconstructing
historic NUTS/Kreis boundary vintages is out of scope for this first pass.

Like `01_download_mastr.py`, this processes **one technology file at a time**
(`paths.mastr_units_raw_path` holds one parquet per technology, largest being
solar's ~6.3M rows) rather than concatenating everything into one dataframe
first — on this memory-constrained machine, holding all technologies at once
was the difference between finishing and being OOM-killed.

## Behind-the-meter PV classification

For grid-level demand/generation modeling, what matters isn't just how much
solar capacity exists, but how much of it feeds straight into the grid vs.
how much is consumed behind the meter first. Each solar unit is classified
into one of three `pv_category` values, using MaStR's own `feed_in_type`
field (`Einspeisungsart`) plus a location-based join against storage units:

- `full_feed_in`: `feed_in_type == "Volleinspeisung"` — no self-consumption,
  the unit's whole output goes to the grid. Confirmed by size too: these
  units average ~61 kW vs. ~10 kW for the other category, i.e. mostly
  commercial/utility-scale installations that sell 100% of output.
- `self_consumption_with_storage`: partial feed-in
  (`"Teileinspeisung (einschließlich Eigenverbrauch)"`) *and* a battery
  storage unit registered at the same `location_id` — home/business PV+battery,
  where even more of the output is likely shaved behind the meter.
- `self_consumption_no_storage`: partial feed-in, no co-located storage.
- `unknown`: `feed_in_type` missing (~0.3% of solar capacity).

The location-based storage join (shared `location_id` between a solar and a
storage unit) was chosen over MaStR's own `SpeicherAmGleichenOrt` ("storage at
same location") field, which turned out to hold nonsense values (e.g. "andere
Gase" / "other gases" — a mismapped catalog code), and over storage's
`co_registered_solar_unit_id` field: on the same population (2.65M storage
units), the explicit field only flags 42.5% as solar-linked, vs. 73.3% via
the location join.

## Monthly export

`capacity_by_region_month_file` covers solar (split into the 3 pv_category
sub-types), storage, and onshore wind, by NUTS3 region; `capacity_by_offshore_month_file`
covers offshore wind by its two pseudo-regions. Both start 2015-01 (fixed;
independent of when the data itself starts) and run to the current month.

Monthly snapshots use the same "installed as of the end of the period" rule
as the annual panel, but computed differently: looping over ~300 months and
re-filtering millions of rows each time (fine for ~30 annual snapshots) is far
too slow. Instead, `monthly_snapshot_panel` adds +capacity at a unit's
commissioning month and -capacity at its shutdown month (if any), then takes
a *cumulative sum along the month axis* per group — a unit contributes to
every month from commissioning up to (excluding) its shutdown month. This
turns "300 passes over the whole table" into a handful of groupby/cumsum
calls over a much smaller (region x month) grid.

## Offshore region polygons

`offshore_regions_file` holds one polygon per offshore cluster: the convex
hull (via shapely) of every currently-installed offshore turbine's real
coordinates. This used to be computed inline in the EDA notebook; it's built
here instead so the hull-construction logic exists in exactly one place, and
the notebook (and this monthly export) both just read the result.
"""

import gc

import geopandas as gpd
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from mpg.paths import ProjPaths
from shapely.geometry import MultiPoint

paths = ProjPaths()
paths.ensure_directories()

OFFSHORE_NORTH_SEA_CODE = "DEZZ-NORDSEE"
OFFSHORE_BALTIC_SEA_CODE = "DEZZ-OSTSEE"

EVENT_COLUMNS = [
    "unit_id",
    "technology",
    "region_code",
    "state",
    "capacity_mw",
    "commissioning_date",
    "final_shutdown_date",
    "unit_operational_status",
    "longitude",
    "latitude",
    "pv_category",
    "usage_sector",
    "installation_type",
]

EXPORT_START_PERIOD = pd.Period("2015-01", freq="M")


def monthly_snapshot_panel(df: pd.DataFrame, group_cols: list[str], month_range: pd.PeriodIndex) -> pd.DataFrame:
    """Installed capacity_mw + unit_count per group, for every month in `month_range`.

    Vectorized cumulative-delta approach — see module docstring ("Monthly
    export") for why this replaces a naive per-month filter+groupby loop.
    """
    start_period = df["commissioning_date"].dt.to_period("M")
    end_period = df["final_shutdown_date"].dt.to_period("M")
    has_end = end_period.notna()

    adds = df[group_cols].copy()
    adds["period"] = start_period
    adds["capacity_delta"] = df["capacity_mw"]
    adds["count_delta"] = 1

    removes = df.loc[has_end, group_cols].copy()
    removes["period"] = end_period[has_end]
    removes["capacity_delta"] = -df.loc[has_end, "capacity_mw"]
    removes["count_delta"] = -1

    net = (
        pd.concat([adds, removes], ignore_index=True)
        .groupby(group_cols + ["period"])[["capacity_delta", "count_delta"]]
        .sum()
    )

    # `unstack` leaves NaN for (group, period) combos with no net change in a
    # period where the group has *some* column already (as opposed to a period
    # missing entirely, which `reindex`'s fill_value handles) — fillna(0)
    # covers both before the cumulative sum.
    capacity = (
        net["capacity_delta"].unstack("period").reindex(columns=month_range, fill_value=0.0)
        .fillna(0.0).cumsum(axis=1)
    )
    unit_count = (
        net["count_delta"].unstack("period").reindex(columns=month_range, fill_value=0)
        .fillna(0).cumsum(axis=1)
    )

    panel = pd.concat(
        [capacity.stack().rename("capacity_mw"), unit_count.stack().rename("unit_count")], axis=1
    ).reset_index()
    panel = panel.rename(columns={"period": "month"})
    panel = panel[panel["month"] >= EXPORT_START_PERIOD].copy()
    panel["month"] = panel["month"].dt.to_timestamp() + pd.offsets.MonthEnd(0)
    return panel.reset_index(drop=True)


correspondence = pd.read_parquet(paths.lau_nuts_correspondence_file)
tech_files = sorted(paths.mastr_units_raw_path.glob("*.parquet"))

# Location IDs that have a storage unit registered — used to flag solar units
# with a co-located battery. Cheap: a single string column, ~2.65M rows.
storage_file = paths.mastr_units_raw_path / "storage.parquet"
storage_locations = set(
    pd.read_parquet(storage_file, columns=["location_id"])["location_id"].dropna()
)

# First pass: cheapest possible read (one column) to find the overall start year.
min_years = []
for f in tech_files:
    dates = pd.to_datetime(
        pd.read_parquet(f, columns=["commissioning_date"])["commissioning_date"],
        errors="coerce",
    ).dropna()
    if len(dates):
        min_years.append(dates.min().year)
start_year = min(min_years)
end_year = pd.Timestamp.today().year

# Full history is needed for the cumulative-sum in monthly_snapshot_panel to
# be correct (a unit commissioned before 2015 still contributes capacity in
# 2015); EXPORT_START_PERIOD trims the *output* to 2015 onward afterward.
MONTH_RANGE = pd.period_range(
    start=f"{start_year}-01", end=pd.Timestamp.today().to_period("M"), freq="M", name="period"
)

events_writer = None
partial_panels = []
partial_pv_panels = []
partial_region_month_panels = []
partial_offshore_month_panels = []
offshore_region_rows = []
total_rows = 0
total_events = 0
unmatched_total = 0

for f in tech_files:
    units = pd.read_parquet(f)
    total_rows += len(units)
    units["pv_category"] = None
    # usage_sector/installation_type already exist as real columns in solar's
    # raw file (see 01_download_mastr.py) — only fill them in as an all-None
    # placeholder for the other technologies, don't clobber solar's data.
    for col in ("usage_sector", "installation_type"):
        if col not in units.columns:
            units[col] = None

    units["municipality_key"] = (
        units["municipality_key"].astype(str).str.extract(r"(\d+)")[0].str.zfill(8)
    )

    # ── Assign region: NUTS3 via municipality key, offshore wind via sea location ─
    # (MaStR's grid-cluster fields for offshore wind are empty in practice; the
    # `sea_location` field ("Nordsee"/"Ostsee") is what's actually populated.)
    units = units.merge(correspondence, how="left", on="municipality_key")
    units["region_code"] = units["nuts3_code"]
    if "sea_location" in units.columns:
        units.loc[units["sea_location"] == "Nordsee", "region_code"] = OFFSHORE_NORTH_SEA_CODE
        units.loc[units["sea_location"] == "Ostsee", "region_code"] = OFFSHORE_BALTIC_SEA_CODE

    unmatched = units["region_code"].isna()
    unmatched_total += int(unmatched.sum())
    units = units[~unmatched].copy()

    # ── Behind-the-meter PV classification (solar only) — see module docstring ─
    if "feed_in_type" in units.columns:
        has_storage = units["location_id"].isin(storage_locations)
        is_full_feed_in = units["feed_in_type"] == "Volleinspeisung"
        is_partial_feed_in = units["feed_in_type"].astype(str).str.startswith("Teileinspeisung")

        units.loc[is_full_feed_in, "pv_category"] = "full_feed_in"
        units.loc[is_partial_feed_in & has_storage, "pv_category"] = "self_consumption_with_storage"
        units.loc[is_partial_feed_in & ~has_storage, "pv_category"] = "self_consumption_no_storage"
        units["pv_category"] = units["pv_category"].fillna("unknown")

    # ── Harmonize capacity + dates ────────────────────────────────────────────
    units["capacity_mw"] = units["net_capacity_kw"].astype(float) / 1000.0
    units["commissioning_date"] = pd.to_datetime(units["commissioning_date"], errors="coerce")
    units["final_shutdown_date"] = pd.to_datetime(units["final_shutdown_date"], errors="coerce")
    units = units[units["commissioning_date"].notna() & (units["capacity_mw"] > 0)].copy()

    # Not cast to category here: a per-file category dictionary would need a
    # different index width (int8 vs int16) depending on how many distinct
    # regions/technologies appear in *that* file, and pyarrow's ParquetWriter
    # requires an identical schema across all write_table() calls. Parquet
    # dictionary-encodes repeated strings on disk regardless of pandas dtype,
    # so this doesn't cost us the compression, only the in-memory shortcut.
    events = units[EVENT_COLUMNS].reset_index(drop=True)
    events["region_code"] = events["region_code"].astype(str)
    events["technology"] = events["technology"].astype(str)
    # pandas' nullable "string" dtype (not plain object, not category) so
    # that these columns convert to the same pyarrow `large_string` type
    # for every technology: an all-None plain object column (every
    # non-solar technology) infers as pyarrow's `null` type instead, and
    # solar's own category dtype (see 01_download_mastr.py) would carry a
    # dictionary encoding that other files don't have — either mismatch
    # breaks the shared ParquetWriter across technologies.
    for col in ("pv_category", "usage_sector", "installation_type"):
        events[col] = events[col].astype("string")
    total_events += len(events)

    arrow_table = pa.Table.from_pandas(events, preserve_index=False)
    if events_writer is None:
        events_writer = pq.ParquetWriter(paths.capacity_events_file, arrow_table.schema)
    events_writer.write_table(arrow_table)

    # ── Annual snapshot panel, for this technology only ───────────────────────
    tech_snapshots = []
    for year in range(start_year, end_year + 1):
        snapshot_date = pd.Timestamp(year=year, month=12, day=31)
        installed = events["commissioning_date"] <= snapshot_date
        still_online = events["final_shutdown_date"].isna() | (
            events["final_shutdown_date"] > snapshot_date
        )
        online = events[installed & still_online]
        if online.empty:
            continue
        panel = (
            online.groupby(["region_code", "technology"], observed=True)
            .agg(capacity_mw=("capacity_mw", "sum"), unit_count=("unit_id", "count"))
            .reset_index()
        )
        panel["year"] = year
        tech_snapshots.append(panel)
    if tech_snapshots:
        partial_panels.append(pd.concat(tech_snapshots, ignore_index=True))

    # ── Annual snapshot panel by pv_category (solar only) ─────────────────────
    if f.stem == "solar":
        pv_snapshots = []
        for year in range(start_year, end_year + 1):
            snapshot_date = pd.Timestamp(year=year, month=12, day=31)
            installed = events["commissioning_date"] <= snapshot_date
            still_online = events["final_shutdown_date"].isna() | (
                events["final_shutdown_date"] > snapshot_date
            )
            online = events[installed & still_online]
            if online.empty:
                continue
            pv_panel = (
                online.groupby(["region_code", "pv_category"], observed=True)
                .agg(capacity_mw=("capacity_mw", "sum"), unit_count=("unit_id", "count"))
                .reset_index()
            )
            pv_panel["year"] = year
            pv_snapshots.append(pv_panel)
        if pv_snapshots:
            partial_pv_panels.append(pd.concat(pv_snapshots, ignore_index=True))

    # ── Monthly export panels (solar/storage/wind only) — see module docstring ─
    if f.stem == "solar":
        monthly = monthly_snapshot_panel(events, ["region_code", "pv_category"], MONTH_RANGE)
        monthly["series"] = "solar_" + monthly["pv_category"].astype(str)
        partial_region_month_panels.append(monthly.drop(columns=["pv_category"]))

    elif f.stem == "storage":
        monthly = monthly_snapshot_panel(events, ["region_code"], MONTH_RANGE)
        monthly["series"] = "storage"
        partial_region_month_panels.append(monthly)

    elif f.stem == "wind":
        monthly = monthly_snapshot_panel(events, ["region_code"], MONTH_RANGE)
        is_offshore_row = monthly["region_code"].str.startswith("DEZZ")
        onshore_monthly = monthly[~is_offshore_row].copy()
        onshore_monthly["series"] = "wind_onshore"
        partial_region_month_panels.append(onshore_monthly)
        partial_offshore_month_panels.append(monthly[is_offshore_row].copy())

        # ── Offshore region polygons (built once, here — see module docstring) ─
        today = pd.Timestamp.today()
        offshore_now = events[
            events["region_code"].str.startswith("DEZZ")
            & (events["commissioning_date"] <= today)
            & (events["final_shutdown_date"].isna() | (events["final_shutdown_date"] > today))
        ].dropna(subset=["longitude", "latitude"])
        for region_code, grp in offshore_now.groupby("region_code"):
            hull = MultiPoint(list(zip(grp["longitude"], grp["latitude"]))).convex_hull
            offshore_region_rows.append(
                {
                    "region_code": region_code,
                    "capacity_mw": grp["capacity_mw"].sum(),
                    "turbine_count": len(grp),
                    "geometry": hull,
                }
            )

    print(f"  {f.stem}: {len(units):,} units with a region assigned")

    del units, events, tech_snapshots, arrow_table
    gc.collect()

if events_writer is not None:
    events_writer.close()
print(
    f"Saved {total_events:,} unit-level capacity events "
    f"(dropped {unmatched_total:,} of {total_rows:,} with no region assigned) "
    f"-> {paths.capacity_events_file}"
)

capacity_by_region_year = pd.concat(partial_panels, ignore_index=True)
capacity_by_region_year.to_parquet(paths.capacity_by_region_year_file, index=False)
print(
    f"Saved annual capacity panel: {len(capacity_by_region_year):,} rows, "
    f"years {start_year}-{end_year} -> {paths.capacity_by_region_year_file}"
)

capacity_by_region_year_pv_category = pd.concat(partial_pv_panels, ignore_index=True)
capacity_by_region_year_pv_category.to_parquet(paths.capacity_by_region_year_pv_category_file, index=False)
print(
    f"Saved annual PV-category panel: {len(capacity_by_region_year_pv_category):,} rows "
    f"-> {paths.capacity_by_region_year_pv_category_file}"
)

capacity_by_region_month = pd.concat(partial_region_month_panels, ignore_index=True)
capacity_by_region_month.to_parquet(paths.capacity_by_region_month_file, index=False)
print(
    f"Saved monthly region export: {len(capacity_by_region_month):,} rows, "
    f"from {EXPORT_START_PERIOD} -> {paths.capacity_by_region_month_file}"
)

capacity_by_offshore_month = pd.concat(partial_offshore_month_panels, ignore_index=True)
capacity_by_offshore_month.to_parquet(paths.capacity_by_offshore_month_file, index=False)
print(
    f"Saved monthly offshore export: {len(capacity_by_offshore_month):,} rows "
    f"-> {paths.capacity_by_offshore_month_file}"
)

offshore_regions = gpd.GeoDataFrame(offshore_region_rows, crs="EPSG:4326")
offshore_regions.to_file(paths.offshore_regions_file, driver="GeoJSON")
print(f"Saved {len(offshore_regions):,} offshore region polygons -> {paths.offshore_regions_file}")
