"""Download PECD v4.2 wind zone region masks (PEON onshore, PEOF offshore).

Pure data acquisition — no charts. PECD v4.2 (the Pan-European Climate
Database, co-developed by C3S/ENTSO-E) offers no NUTS-level spatial
aggregation for wind capacity factors — only two pan-European zone schemes:
PEON (onshore) and PEOF (offshore). Germany intersects 7 PEON zones
(`DE01`..`DE07`) and 6 PEOF zones (`DE011_OFF`..`DE015_OFF`, `DE02_OFF`). See
`~/research/delu-headline-forecast/docs/data_sources.md` for the full
background (this project doesn't consume PECD's actual weather/capacity-factor
timeseries, only the zone geometry, to fractionally regroup MaStR wind
capacity by zone in `pipeline/07_build_wind_zone_panel.py`).

The zone boundaries aren't published as a shapefile, but the CDS "weights and
masks" widget provides the same information rasterized: a NetCDF per scheme
giving each 0.25-degree grid cell's fractional area coverage (0-1) for every
European zone.

Requires a ~/.cdsapirc file with a valid CDS API key.
"""

import zipfile

import cdsapi
from mpg.paths import ProjPaths

paths = ProjPaths()
paths.ensure_directories()

MASKS = {
    "peon": paths.peon_mask_file,
    "peof": paths.peof_mask_file,
}

client = cdsapi.Client()

for variable, output_file in MASKS.items():
    if output_file.exists():
        print(f"{variable}: already downloaded -> {output_file}")
        continue

    zip_path = output_file.with_suffix(".zip")
    request = {
        "pecd_version": "pecd4_2",
        "file_version": "fv1",
        "variable": f"{variable}_region_mask",
    }
    print(f"{variable}: requesting mask ...")
    client.retrieve("sis-energy-pecd", request, str(zip_path))

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        assert len(names) == 1, f"expected a single file in {zip_path.name}, got {names}"
        with z.open(names[0]) as src, open(output_file, "wb") as dst:
            dst.write(src.read())
    zip_path.unlink()
    print(f"  saved -> {output_file}")
