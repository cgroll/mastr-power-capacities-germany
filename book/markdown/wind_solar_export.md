---
title: "Wind + Solar Unit Export"
---

# Purpose

`pipeline/10_export_wind_solar_units.py` produces a small, general-purpose
extract — `mastr_units_wind_solar.parquet` plus two small PECD region-mask
lookup tables — for downstream projects that want raw(ish) wind/solar MaStR
data without paying this project's own setup cost (the ~12 GB bulk dump,
`open-mastr` parsing, region assignment). It's deliberately **not**
region-assigned to a PEON/PEOF/NUTS2 zone beyond MaStR's own `region_code`,
not classified into PECD's solar technology codes, and not aggregated by
month — those steps are left to the consumer, either because they're the
actual point of a given downstream analysis (see
`~/research/hackathon-power-system-planning`, the first consumer, which
uses this export as the raw-data ingredient for a validation exercise) or
because different consumers will want to do them differently.

If you want an already-aggregated panel instead, see
`capacity_by_region_month_file` / `capacity_by_nuts2_month_file` /
`capacity_by_peon_month_file` / `capacity_by_peof_month_file` — this
export is deliberately upstream of all of those.

# Where the underlying data comes from

- **MaStR itself**: the Marktstammdatenregister, Germany's public register
  of essentially every unit in the electricity and gas market. Official
  bulk XML export (refreshed daily):
  <https://www.marktstammdatenregister.de/MaStR/Datendownload>. The raw
  export is a multi-GB ZIP (a few GB compressed; the parsed SQLite
  database this project builds from it is closer to 10 GB) — see
  `pipeline/01_download_mastr.py` for the download/parsing approach
  (via [open-mastr](https://github.com/OpenEnergyPlatform/open-MaStR)) and
  its notes on the memory pitfalls of processing solar's ~6.3M rows
  naively.
- **PEON/PEOF region masks**: Copernicus Climate Data Store, PECD v4.2,
  <https://cds.climate.copernicus.eu/datasets/sis-energy-pecd> — a
  rasterized 0.25°×0.25° grid of each cell's fractional coverage by every
  European wind zone (see `pipeline/06_download_pecd_masks.py`).

# How region assignment actually works (done upstream, in `pipeline/03`)

Every MaStR unit is registered with a *Gemeindeschlüssel* (the official
German municipality key, "AGS") — not a postal code, which doesn't align
with administrative boundaries. For onshore units, that key is matched
against a published Destatis/Eurostat municipality→NUTS correspondence
table to get a NUTS3 region code (e.g. `DE111`). Offshore wind units have
no municipality, so they instead get a code built from MaStR's own
`sea_location` field: `DEZZ-NORDSEE` / `DEZZ-OSTSEE`. `DEZZ` itself is a
real, official Eurostat NUTS2-level code — the "Extra-Regio" designation
for territory (like offshore waters) outside the regular NUTS grid; the
`-NORDSEE`/`-OSTSEE` suffix splitting it into the two seas is this
project's own convention, not an official code.

# Column reference: `mastr_units_wind_solar.parquet`

~6.27M rows (6,234,356 solar, 34,930 wind).

| Column | Meaning | Notes / caveats |
|---|---|---|
| `technology` | `"solar"` or `"wind"` | Onshore/offshore not split — see `region_code`. |
| `region_code` | NUTS3 code (onshore) or `DEZZ-NORDSEE`/`DEZZ-OSTSEE` (offshore wind) | See region-assignment section above. |
| `capacity_mw` | Installed electrical capacity | Solar median ≈ 0.007 MW; wind median ≈ 2.0 MW. |
| `commissioning_date` | Commissioning date | **Caveat**: the dataset minimum is 1900-01-01 for some solar units — almost certainly a placeholder for "unknown," not a real 1900 installation. |
| `final_shutdown_date` | Decommissioning date | Mostly `NaT` (98.8% solar, 91.7% wind) — meaning still active. |
| `longitude` / `latitude` | Unit coordinates | ~4% populated for solar (not needed for its NUTS-code-based region assignment), ~97% for wind (~3% missing is a real gap). |
| `installation_type` | Rooftop / balcony ("Steckerfertige Solaranlage") / ground-mounted ("Freiflächensolaranlage") / other | Solar-only. Ground-mounted vs. rooftop is the primary axis for PECD's utility-vs-residential/industrial technology split. |
| `usage_sector` | Household / commerce / industry / agriculture / public / other | Solar-only, ~27% missing (missing defaults to residential in the classification convention below — dominated by balcony systems). |
| `pv_category` | `full_feed_in` / `self_consumption_no_storage` / `self_consumption_with_storage` / `unknown` | Solar-only. A *different* axis from technology/installation type — see `capacity_by_region_year_pv_category_file` for this project's own use of it (behind-the-meter / self-consumption analysis). |
| `main_orientation` | Compass orientation, or `"nachgeführt"` (tracked) | Solar-only, ~20% missing. Only ~5,700 units are tracked. |
| `main_orientation_tilt_bucket` | Tilt-angle bucket, or `"Nachgeführt"` | Solar-only, same missingness pattern as orientation. |

No `unit_id`: it's used internally to join `main_orientation`/
`main_orientation_tilt_bucket` in from `mastr_technical_detail_file("solar")`
(a separate raw table), then dropped — fully unique per row, so keeping it
would roughly triple the file size for no benefit once the join is done.

# Column reference: `pecd_region_mask_{peon,peof}.parquet`

Columns: `zone_id`, `latitude`, `longitude`, `weight`. One row per (zone,
0.25° grid cell) pair with nonzero coverage — `weight` is the fraction of
that cell's area inside that zone. Cropped from the full-Europe raster
(`peon_mask_file` / `peof_mask_file`) to Germany's own zones (PEON: 7
zones `DE01`–`DE07`; PEOF: 6 zones `DE011_OFF`...`DE02_OFF`) and a
bounding box around Germany — 995 / 233 rows.

# Recipe for a downstream consumer

1. **Zone assignment.** Solar: `region_code.str[:4]` (NUTS3→NUTS2, a
   strict-prefix relationship in Eurostat's scheme). Wind: round
   (longitude, latitude) to the nearest 0.25° grid point, then look up
   that point's zone weights in the matching mask file; split a unit's
   capacity across zones proportional to weight where a cell straddles
   more than one (don't just pick the largest).
2. **Onshore/offshore split.** `region_code` starting with `"DEZZ"` is
   offshore.
3. **Solar technology classification** (PECD codes 60/61/62/63): ground-mounted
   (`installation_type == "Freiflächensolaranlage"`) → utility-scale
   (62/63, split further by whether `main_orientation`/
   `main_orientation_tilt_bucket` indicates tracking); everything else →
   rooftop (60/61, split by `usage_sector == "Haushalt"` or missing →
   residential, else industrial).
4. **Time-varying capacity.** A unit counts as installed in a given month
   if `commissioning_date` is on or before it and `final_shutdown_date` is
   missing or after it.
