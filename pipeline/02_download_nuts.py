"""Download German NUTS region geometries and the LAU->NUTS3 crosswalk.

Pure data script — no visualizations.

Two Eurostat/GISCO sources, both public and unauthenticated:
- NUTS region geometries (all levels, all EU countries) as GeoJSON.
- The LAU/NUTS correspondence table, which maps every German municipality
  (LAU code == 8-digit Gemeindeschluessel/AGS) to its NUTS3 region. This is
  used downstream to join MaStR units (which carry the AGS) to NUTS3 regions,
  which is far more robust than string-matching district names.

Also keeps country-level (LEVL_CODE 0) outlines for Germany's North/Baltic Sea
neighbors, for map context around the offshore wind areas (which sit in
international/German waters between these countries, outside any NUTS region);
and for Luxembourg, whose outline unioned with Germany's gives the DE-LU day-ahead
electricity bidding zone boundary (Luxembourg has no TSO of its own and has been
merged into Germany's bidding zone since October 2018).
"""

import geopandas as gpd
import pandas as pd
import requests
from mpg.paths import ProjPaths

paths = ProjPaths()
paths.ensure_directories()

NUTS_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/"
    "NUTS_RG_01M_2024_4326.geojson"
)
LAU_NUTS_URL = (
    "https://ec.europa.eu/eurostat/documents/345175/501971/"
    "EU-27-LAU-2024-NUTS-2024.xlsx"
)
NEIGHBOR_COUNTRIES = ["DE", "NL", "BE", "DK", "PL", "SE", "LU"]

nuts = gpd.read_file(NUTS_URL)

# ── NUTS region geometries (Germany only) ─────────────────────────────────────
nuts_de = nuts[nuts["CNTR_CODE"] == "DE"][
    ["NUTS_ID", "LEVL_CODE", "NUTS_NAME", "NAME_LATN", "geometry"]
].reset_index(drop=True)
nuts_de.to_file(paths.nuts_regions_file, driver="GeoJSON")
print(f"Saved {len(nuts_de):,} NUTS regions (levels 0-3) -> {paths.nuts_regions_file}")

# ── Country outlines: North/Baltic Sea context + DE-LU bidding zone ──────────
country_borders = nuts[(nuts["LEVL_CODE"] == 0) & (nuts["CNTR_CODE"].isin(NEIGHBOR_COUNTRIES))][
    ["CNTR_CODE", "NAME_LATN", "geometry"]
].reset_index(drop=True)
country_borders.to_file(paths.country_borders_file, driver="GeoJSON")
print(f"Saved {len(country_borders):,} country outlines -> {paths.country_borders_file}")

# ── LAU -> NUTS3 correspondence (Germany sheet) ───────────────────────────────
correspondence_raw = pd.read_excel(LAU_NUTS_URL, sheet_name="DE")
correspondence = correspondence_raw[["LAU CODE", "NUTS3"]].rename(
    columns={"LAU CODE": "municipality_key", "NUTS3": "nuts3_code"}
)
correspondence["municipality_key"] = correspondence["municipality_key"].astype(str).str.zfill(8)
correspondence.to_parquet(paths.lau_nuts_correspondence_file, index=False)
print(
    f"Saved {len(correspondence):,} municipality -> NUTS3 mappings "
    f"-> {paths.lau_nuts_correspondence_file}"
)
