# Contribution Conventions

This document describes the project structure and conventions.
It is written for human contributors and AI agents alike.

## Project Structure

```
project-root/
├── pkg/                     # Python package — shared utilities
│   ├── __init__.py
│   └── paths.py             # Centralized path configuration
├── pipeline/                # Data pipeline scripts
│   ├── 01_download_*.py     # Pure data acquisition (no charts)
│   ├── 02_analyse_*.py      # Analysis scripts → become book notebooks
│   └── _strip_jupytext_metadata.py  # Shared post-processing helper
├── book/                    # MyST Jupyter Book source
│   ├── notebooks/           # Executed .ipynb files (produced by DVC)
│   ├── markdown/            # Static hand-written content
│   └── myst.yml             # Book configuration and table of contents
├── data/
│   ├── downloads/           # Raw downloaded data (git-ignored, DVC-cached)
│   └── processed/           # Processed/transformed data (git-ignored, DVC-cached)
├── output/
│   ├── images/              # Chart images saved by pipeline scripts
│   └── reports/             # Report files
├── dvc.yaml                 # Pipeline definition (stages, deps, outs)
├── dvc.lock                 # Pipeline state (checksums) — tracked in git
└── pyproject.toml           # Dependencies managed by uv
```

## Tools

| Tool | Purpose |
|------|---------|
| **uv** | Package and environment management |
| **DVC** | Pipeline orchestration (dependency-aware task runner) |
| **jupytext** | Execute `.py` analysis scripts → `.ipynb` notebooks |
| **MyST / mystmd** | Build the HTML book from notebooks and markdown |

## DVC Primer

[DVC](https://dvc.org/) is a data-version-control and pipeline tool. It reads
the `dvc.yaml` file in the project root and tracks stage state in `dvc.lock`.

### Core concept: stages

A stage declares *how* to produce outputs from dependencies:

```yaml
stages:
  my_stage:
    cmd: MPLBACKEND=Agg uv run jupytext ...
    deps:
      - pipeline/02_analyse.py
      - data/downloads/raw.parquet
    outs:
      - book/notebooks/02_analyse.ipynb:
          cache: false
      - output/images/02_chart.png:
          cache: false
```

DVC hashes `cmd`, every `deps` entry, and compares against `dvc.lock`: if
nothing changed, the stage is skipped. This is the key difference from
Snakemake — there are no file-modification-timestamp comparisons, hashes
drive incremental builds, and the result is recorded in `dvc.lock` (which
must be committed to git).

### `cache: false` for git-tracked outputs

By default DVC moves stage outputs into its own cache and git-ignores them —
appropriate for `data/downloads/` and `data/processed/`. But
`book/notebooks/*.ipynb` and `output/images/*.png` should stay as normal
files tracked directly by git (see [Git Conventions](#git-conventions)), so
every such output is declared with `cache: false`. DVC still hashes the file
to detect staleness; it just doesn't duplicate it into `.dvc/cache`.

### `persist: true` for downloaded data

Downloaded files should not be wiped out and re-fetched every run. Mark
their output with `persist: true` so DVC leaves the existing file in place
whenever the stage is (re-)run:

```yaml
stages:
  download_data:
    cmd: uv run python pipeline/01_download.py
    deps:
      - pipeline/01_download.py
    outs:
      - data/downloads/raw.parquet:
          persist: true
```

To force a fresh download: delete the file (or run `dvc repro -f
download_data`).

### Running the pipeline

```bash
dvc repro --dry        # dry-run: show what would execute
dvc repro               # run the full pipeline (skips up-to-date stages)
dvc repro <stage>       # build one specific stage (and its dependencies)
dvc repro -f <stage>    # force-re-run a specific stage
dvc repro --force       # re-run everything unconditionally
dvc dag                 # print the pipeline DAG
```

Or via Make shortcuts:

```bash
make run       # dvc repro
make dry-run   # dvc repro --dry
make serve     # myst start (local book preview)
```

### The `dvc.yaml` convention

`dvc.yaml` lists every stage; DVC infers the full DAG from each stage's
`deps`/`outs`, so there is no separate "build everything" target to
maintain — running bare `dvc repro` builds every stage that is out of date.

## Pipeline Conventions

### Two types of scripts

**1. Pure data scripts** (`01_*`, `00_*`, …)
- No charts or visualizations.
- Read/write data files only.
- Registered in `dvc.yaml` with `persist: true` outputs to avoid re-downloading.
- Not converted to notebooks.

**2. Analysis scripts** (`02_*`, `03_*`, …)
- Use jupytext `# %%` cell markers and a jupytext/kernelspec header.
- Save all figures to `output/images/` via `fig.savefig()`.
- Use MyST `{figure}` directives in `# %% [markdown]` cells.
- DVC runs them via jupytext → produces an executed `.ipynb` in `book/notebooks/`.

### Jupytext header for analysis scripts

```python
# ---
# jupytext:
#   text_representation:
#     format_name: percent
# kernelspec:
#   display_name: Python 3
#   language: python
#   name: python3
# ---
```

### Saving figures and referencing them

```python
# %%
fig, ax = plt.subplots(figsize=(14, 4))
ax.plot(...)
fig.savefig(paths.images_path / "03_my_chart.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/03_my_chart.png
# :name: fig-03-my-chart
# Caption describing the figure.
# ```
```

The path `../../output/images/` is relative to `book/notebooks/` where the
generated `.ipynb` lives.

Naming convention: `<script_number>_<descriptive_name>.png`.

### DVC stage for analysis scripts

```yaml
stages:
  process_my_analysis:
    cmd: >-
      MPLBACKEND=Agg uv run jupytext --to notebook --execute
      --set-kernel python3
      --output book/notebooks/03_my_analysis.ipynb
      pipeline/03_my_analysis.py &&
      uv run python pipeline/_strip_jupytext_metadata.py
      book/notebooks/03_my_analysis.ipynb
    deps:
      - pipeline/03_my_analysis.py
      - data/downloads/raw.parquet
    outs:
      - book/notebooks/03_my_analysis.ipynb:
          cache: false
      - output/images/03_my_chart.png:
          cache: false
```

`pipeline/_strip_jupytext_metadata.py` strips the raw jupytext metadata cell
that MyST does not recognize; every analysis stage's `cmd` calls it as a
second step. The `MPLBACKEND=Agg` environment variable makes `plt.show()` a
no-op in headless mode.

## Path Conventions

All scripts must be runnable from any working directory. Use `ProjPaths`
from `pkg/paths.py`:

```python
from pkg.paths import ProjPaths

paths = ProjPaths()

df = pd.read_parquet(paths.example_raw_file)
fig.savefig(paths.images_path / "03_chart.png")
```

Key paths:

| Property | Directory |
|----------|-----------|
| `paths.data_path` | `data/` |
| `paths.downloads_path` | `data/downloads/` |
| `paths.processed_data_path` | `data/processed/` |
| `paths.images_path` | `output/images/` |
| `paths.pipeline_path` | `pipeline/` |

## Adding a New Pipeline Stage

1. **Write the script** in `pipeline/`.
2. **Add a property** to `pkg/paths.py` for every new data file:
   ```python
   @property
   def my_new_file(self) -> Path:
       """One-line description."""
       return self.downloads_path / "my_data.parquet"
   ```
3. **Add a stage** to `dvc.yaml` with `cmd`, `deps`, and `outs` (use
   `cache: false` for anything under `book/notebooks/` or `output/images/`,
   and `persist: true` for downloaded data).
4. **Add the notebook** to the `toc` in `book/myst.yml`.

## Git Conventions

| Tracked | Not tracked |
|---------|-------------|
| `pipeline/*.py` source files | `data/downloads/*` |
| `book/notebooks/*.ipynb` generated notebooks | `data/processed/*` |
| `output/images/*.png` generated charts | `.venv/` |
| `book/markdown/*.md` static content | |
| `dvc.yaml`, `dvc.lock` | |

The `.ipynb` notebooks and images are tracked so the book can be rebuilt
from git without re-running the pipeline (CI only runs `myst build`). This
is why they are declared with `cache: false` in `dvc.yaml` — DVC still
hashes them to detect staleness, but the files themselves live in git, not
in `.dvc/cache`.

## Workflow Summary

```
1. Write pipeline script in pipeline/
2. Add DVC stage in dvc.yaml
3. make run          ← execute pipeline (dvc repro)
4. make serve        ← preview book locally
5. git add / commit  ← commit notebooks + images + dvc.lock
6. git push          ← CI deploys to GitHub Pages
```
