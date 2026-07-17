"""Download and consolidate MaStR renewable generation + storage units.

Pure data script — no visualizations. Uses the `open-mastr` package to fetch
the official Marktstammdatenregister (MaStR) bulk dump, parse it into a local
SQLite database, and apply open-mastr's own decoding/cleansing (German codes
-> human-readable labels, dtypes).

Note: despite the package docs advertising English column translation, the
per-technology tables in open-mastr 0.17.1 (`<tech>_extended`) keep the
original German column names (confirmed by inspecting the live SQLite schema
after a real download) — so the column list below uses German names.

Scope is renewables + storage: wind, solar, biomass, hydro, gsgk (geothermal /
mine gas / pressure relaxation), and electricity storage. Each technology's
database table is read, reduced to a harmonized column set, and written to
its own parquet file (`paths.mastr_units_raw_path / "<technology>.parquet"`).

This machine has 14GB RAM and is usually running other memory-hungry apps, so
every step here is deliberately chunked/streamed rather than loading full
tables into pandas — solar alone is ~6.3 million rows, and each of the
following blew up memory before this was applied:
- calling `download(data=[...])` for all 6 technologies in one process
  (killed by the OOM killer while parsing solar's XML).
- `pd.read_sql_table(table_name, con=db.engine)` with no column filter,
  loading solar's full ~100-column table (killed at 6.3GB resident, per
  `journalctl -k`).
- even with column filtering, loading solar's 6.3M rows in one
  `read_sql_table` call (killed again, exit 137).

The fixes applied:
- technologies are downloaded and parsed **one at a time**, and the whole
  script is idempotent (skips a technology's download if its DB table
  already has rows, skips reprocessing if its output parquet already
  exists) — so an interrupted run resumes cheaply instead of redoing
  multi-minute XML parsing.
- column selection happens in the SQL query itself (`columns=` on
  `read_sql_table`), not by loading everything and reindexing afterward.
- rows are streamed in chunks (`chunksize=`) and written incrementally with
  a `pyarrow.parquet.ParquetWriter`, so peak memory is bounded to one chunk
  (~200k rows), never the full table.
- low-cardinality text columns are cast to `category` dtype and
  coordinate/capacity floats downcast to float32 before writing, so the
  parquet files (and anything reading them back later) stay compact.
"""

import gc
import os

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from sqlalchemy import func, inspect as sa_inspect, select, table as sa_table
from mpg.paths import ProjPaths

paths = ProjPaths()
paths.ensure_directories()

# open-mastr writes its SQLite DB / XML+doc cache under OUTPUT_PATH instead of
# the default $HOME/.open-MaStR, keeping everything self-contained in the repo.
os.environ["OUTPUT_PATH"] = str(paths.mastr_home_path)

from open_mastr import Mastr  # noqa: E402  (import after OUTPUT_PATH is set)

CHUNK_SIZE = 200_000

TECHNOLOGY_TABLES = {
    "wind": "wind_extended",
    "solar": "solar_extended",
    "biomass": "biomass_extended",
    "hydro": "hydro_extended",
    "gsgk": "gsgk_extended",
    "storage": "storage_extended",
}

# Columns present across (most) technology tables (original German names —
# see module docstring).
COMMON_COLUMNS = [
    "EinheitMastrNummer",
    "Energietraeger",
    "Bundesland",
    "Landkreis",
    "Gemeindeschluessel",
    "Postleitzahl",
    "Laengengrad",
    "Breitengrad",
    "Nettonennleistung",
    "Bruttoleistung",
    "Inbetriebnahmedatum",
    "GeplantesInbetriebnahmedatum",
    "DatumEndgueltigeStilllegung",
    "DatumBeginnVoruebergehendeStilllegung",
    "DatumWiederaufnahmeBetrieb",
    "EinheitBetriebsstatus",
    "EinheitSystemstatus",
]
# Technology-specific extra columns, beyond COMMON_COLUMNS.
# wind: `ClusterNordsee`/`ClusterOstsee` (grid cluster) are empty for every
#   offshore unit in practice; `Seelage` ("Nordsee"/"Ostsee") is populated
#   instead and is what we actually use to split offshore capacity by sea
#   (confirmed against the live data: populated for exactly the "Windkraft
#   auf See" rows).
# solar: `Einspeisungsart` (feed-in type: full grid feed-in vs. partial
#   feed-in/self-consumption), `LokationMastrNummer` (site ID, used to join
#   against storage's site ID to detect co-located batteries),
#   `Nutzungsbereich`/`ArtDerSolaranlage` (usage sector / installation type)
#   are kept as cross-checks on the feed-in-type classification.
# storage: `LokationMastrNummer` (site ID, same purpose as for solar),
#   `GemeinsamRegistrierteSolareinheitMastrNummer` (explicit link to a
#   co-registered solar unit, cross-checked against the site-ID join).
TECH_EXTRA_COLUMNS = {
    "wind": ["WindAnLandOderAufSee", "Seelage"],
    "solar": [
        "Einspeisungsart",
        "LokationMastrNummer",
        "Nutzungsbereich",
        "ArtDerSolaranlage",
    ],
    "storage": ["LokationMastrNummer", "GemeinsamRegistrierteSolareinheitMastrNummer"],
}

# Standardized snake_case names used from here on, downstream of this script.
COLUMN_RENAME = {
    "EinheitMastrNummer": "unit_id",
    "Energietraeger": "energy_source",
    "Bundesland": "state",
    "Landkreis": "district",
    "Gemeindeschluessel": "municipality_key",
    "Postleitzahl": "postal_code",
    "Laengengrad": "longitude",
    "Breitengrad": "latitude",
    "Nettonennleistung": "net_capacity_kw",
    "Bruttoleistung": "gross_capacity_kw",
    "Inbetriebnahmedatum": "commissioning_date",
    "GeplantesInbetriebnahmedatum": "planned_commissioning_date",
    "DatumEndgueltigeStilllegung": "final_shutdown_date",
    "DatumBeginnVoruebergehendeStilllegung": "temporary_shutdown_start_date",
    "DatumWiederaufnahmeBetrieb": "resumption_of_operation_date",
    "EinheitBetriebsstatus": "unit_operational_status",
    "EinheitSystemstatus": "unit_system_status",
    "WindAnLandOderAufSee": "wind_onshore_or_offshore",
    "Seelage": "sea_location",
    "Einspeisungsart": "feed_in_type",
    "LokationMastrNummer": "location_id",
    "Nutzungsbereich": "usage_sector",
    "ArtDerSolaranlage": "installation_type",
    "GemeinsamRegistrierteSolareinheitMastrNummer": "co_registered_solar_unit_id",
}

CATEGORY_COLUMNS = [
    "energy_source",
    "state",
    "district",
    "municipality_key",
    "postal_code",
    "unit_operational_status",
    "unit_system_status",
    "wind_onshore_or_offshore",
    "sea_location",
    "feed_in_type",
    "usage_sector",
    "installation_type",
    "technology",
]
FLOAT32_COLUMNS = ["longitude", "latitude", "net_capacity_kw", "gross_capacity_kw"]

db = Mastr()

for technology, table_name in TECHNOLOGY_TABLES.items():
    output_file = paths.mastr_units_raw_path / f"{technology}.parquet"
    if output_file.exists():
        print(f"'{technology}': output file already exists, skipping.")
        continue

    existing_tables = set(sa_inspect(db.engine).get_table_names())
    row_count = 0
    if table_name in existing_tables:
        with db.engine.connect() as conn:
            row_count = conn.execute(
                select(func.count()).select_from(sa_table(table_name))
            ).scalar()

    if row_count > 0:
        print(f"'{technology}' ({table_name}): {row_count:,} rows already in DB, skipping download.")
    else:
        print(f"Downloading + parsing '{technology}' ({table_name})...")
        db.download(data=[technology])

    wanted = COMMON_COLUMNS + TECH_EXTRA_COLUMNS.get(technology, [])
    available = {c["name"] for c in sa_inspect(db.engine).get_columns(table_name)}
    present = [c for c in wanted if c in available]

    writer = None
    row_total = 0
    for chunk in pd.read_sql_table(
        table_name, con=db.engine, columns=present, chunksize=CHUNK_SIZE
    ):
        chunk = chunk.reindex(columns=wanted).rename(columns=COLUMN_RENAME)
        chunk["technology"] = technology

        for col in FLOAT32_COLUMNS:
            if col in chunk:
                chunk[col] = chunk[col].astype("float32")
        for col in CATEGORY_COLUMNS:
            if col in chunk:
                chunk[col] = chunk[col].astype("category")

        arrow_table = pa.Table.from_pandas(chunk, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(output_file, arrow_table.schema)
        writer.write_table(arrow_table)
        row_total += len(chunk)

        del chunk, arrow_table
        gc.collect()

    if writer is not None:
        writer.close()
    print(f"  {table_name}: {row_total:,} rows -> {output_file}")

print(f"Done -> {paths.mastr_units_raw_path}")
