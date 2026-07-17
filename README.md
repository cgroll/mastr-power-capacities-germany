# Mastr Power Capacities Germany

Installed electricity generation and storage capacity in Germany, based on the
[Marktstammdatenregister (MaStR)](https://www.marktstammdatenregister.de/MaStR)
— the German Federal Network Agency's public register of every power/gas unit
in the country. The book publishes an EDA on how installed capacity is
distributed across German NUTS3 regions and how it has changed over time.

The data pipeline is managed by [DVC](https://dvc.org/); dependencies are
managed by [uv](https://docs.astral.sh/uv/); the book is built with
[MyST](https://mystmd.org/) and published to GitHub Pages.

## Data

- **MaStR units** (wind, solar, biomass, hydro, gsgk, storage) via the
  [open-mastr](https://github.com/OpenEnergyPlatform/open-MaStR) package,
  which downloads the official bulk XML dump and applies its own
  decoding/cleansing.
- **NUTS region geometries** and the **LAU→NUTS3 crosswalk** from
  Eurostat/GISCO, used to map each unit's municipality to a NUTS3 region.
  Offshore wind units (no municipality) are assigned to two synthetic
  pseudo-regions by grid cluster (North Sea / Baltic Sea) instead.
- Historic snapshots use **fixed, current NUTS3 boundaries** — only the
  installed-capacity numbers vary by year, not the region geometry.

## Running the pipeline

```bash
uv sync
make dry-run   # preview what would run
make run       # execute the full pipeline (downloads ~GBs of data on first run)
make serve     # open http://localhost:3000 — live book preview
```

## Project layout

```
project-root/
├── mpg/                  # Python package
│   └── paths.py          # Centralized path config
├── pipeline/
│   ├── 01_download_mastr.py         # MaStR bulk download -> consolidated parquet
│   ├── 02_download_nuts.py          # NUTS geometries + LAU-NUTS crosswalk
│   ├── 03_build_capacity_panel.py   # Region assignment + annual capacity panel
│   └── 04_eda.py                    # EDA -> notebook
├── book/                 # MyST book source
│   ├── notebooks/         # Executed notebooks (DVC output)
│   ├── markdown/          # Static content
│   └── myst.yml           # TOC and site settings
├── data/                  # Git-ignored data (cached by DVC)
├── output/images/         # Figures (tracked in git)
├── dvc.yaml               # Pipeline DAG
├── dvc.lock               # Pipeline state (checksums) — tracked in git
└── contribution_conventions.md   # Detailed conventions for contributors/AI
```

See [contribution_conventions.md](contribution_conventions.md) for full details on
adding pipeline stages, writing analysis scripts, and DVC usage.

## Common DVC commands

| Command | Effect |
|---------|--------|
| `dvc repro --dry` | Dry run — show what would execute |
| `dvc repro` | Run pipeline (only rebuilds what's out of date) |
| `dvc repro -f <stage>` | Force-re-run a specific stage |
| `dvc repro <stage>` | Build one specific stage (and its dependencies) |
| `dvc repro --force` | Re-run everything unconditionally |
| `dvc dag` | Print the pipeline DAG |
