# ---
# jupytext:
#   text_representation:
#     format_name: percent
# kernelspec:
#   display_name: Python 3
#   language: python
#   name: python3
# ---

# %% [markdown]
# # EDA: PECD v4.2 wind zones (PEON / PEOF) as raw grid cells
#
# `pipeline/07_build_wind_zone_panel.py` fractionally splits each wind unit's
# capacity across every PEON/PEOF zone with nonzero weight at its 0.25-degree
# grid cell. This notebook visualizes the zone masks that split is based on,
# at the same per-cell resolution the assignment actually uses (rather than
# the dissolved zone outlines a vector polygon view would show): every grid
# cell touched by one of Germany's zones, colored by its highest-weight
# ("winning") zone, with a cell annotated by its top two zones' weights
# whenever more than one zone has nonzero coverage there — i.e. exactly the
# cells where a wind unit's capacity actually gets split across regions,
# rather than assigned whole to one.

# %%
import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from mpg.paths import ProjPaths
from shapely.geometry import box

paths = ProjPaths()

GRID_RESOLUTION_DEG = 0.25
MIN_WEIGHT = 1e-6  # floating-point noise floor below which a zone's coverage doesn't count as "present"

# Fixed categorical hue order (validated for CVD-safe adjacent contrast) — see
# the dataviz skill's reference palette. Direct per-zone + per-cell labels
# (added below) are the mitigation for exceeding the 4-series all-pairs cap.
CATEGORICAL_COLORS = [
    "#2a78d6",  # blue
    "#008300",  # green
    "#e87ba4",  # magenta
    "#eda100",  # yellow
    "#1baf7a",  # aqua
    "#eb6834",  # orange
    "#4a3aa7",  # violet
    "#e34948",  # red
]


def zone_grid_cells(mask_file, zone_prefix: str = "DE") -> tuple[gpd.GeoDataFrame, list[str]]:
    """One row per grid cell touched by any of `zone_prefix`'s zones.

    `zone_id`/`weight` are the cell's argmax (highest-weight) zone; `n_nonzero`
    counts zones with weight > MIN_WEIGHT at that cell; `second_zone`/
    `second_weight` are the runner-up when `n_nonzero` > 1.
    """
    ds = xr.open_dataset(mask_file)
    zones = sorted(z for z in ds["region"].values.tolist() if str(z).startswith(zone_prefix))
    mask_values = ds["mask"].sel(region=zones).values  # (zone, lat, lon)
    lats, lons = ds["latitude"].values, ds["longitude"].values
    ds.close()

    total = mask_values.sum(axis=0)
    lat_idx, lon_idx = np.nonzero(total > 0)

    half = GRID_RESOLUTION_DEG / 2
    rows = []
    for i, j in zip(lat_idx, lon_idx):
        weights = mask_values[:, i, j]
        order = np.argsort(weights)[::-1]
        n_nonzero = int((weights > MIN_WEIGHT).sum())
        rows.append(
            {
                "zone_id": zones[order[0]],
                "weight": weights[order[0]],
                "n_nonzero": n_nonzero,
                "second_zone": zones[order[1]] if n_nonzero > 1 else None,
                "second_weight": weights[order[1]] if n_nonzero > 1 else None,
                "geometry": box(lons[j] - half, lats[i] - half, lons[j] + half, lats[i] + half),
            }
        )
    return gpd.GeoDataFrame(rows, crs="EPSG:4326"), zones


def short_code(zone_id: str) -> str:
    """Compact zone label for in-cell annotations (legend carries the full code)."""
    return zone_id.removeprefix("DE").removesuffix("_OFF")


CELL_INCH = 0.42  # figure inches per 0.25-degree grid cell, tuned so a 2-line annotation fits without overlap
MAP_PAD_DEG = 0.4  # padding added around the cell bounding box when framing the map


def render_zone_map(
    cells: gpd.GeoDataFrame, zones: list[str], title: str, draw_context, annotation_fontsize: float = 5.0
):
    """Build a figure sized to the cell grid's actual extent, so per-cell annotations have room."""
    minx, miny, maxx, maxy = cells.total_bounds
    xlim = (minx - MAP_PAD_DEG, maxx + MAP_PAD_DEG)
    ylim = (miny - MAP_PAD_DEG, maxy + MAP_PAD_DEG)
    n_lon_cells = (xlim[1] - xlim[0]) / GRID_RESOLUTION_DEG
    n_lat_cells = (ylim[1] - ylim[0]) / GRID_RESOLUTION_DEG
    figsize = (max(n_lon_cells * CELL_INCH, 8), max(n_lat_cells * CELL_INCH, 6))

    fig, ax = plt.subplots(figsize=figsize)
    draw_context(ax)

    color_map = dict(zip(zones, CATEGORICAL_COLORS))
    for zone in zones:
        subset = cells[cells["zone_id"] == zone]
        if subset.empty:
            continue
        subset.plot(ax=ax, color=color_map[zone], edgecolor="white", linewidth=0.15, zorder=2)

    boundary_cells = cells[cells["n_nonzero"] > 1]
    for _, row in boundary_cells.iterrows():
        centroid = row.geometry.centroid
        label = f"{short_code(row['zone_id'])} {row['weight']:.2f}\n{short_code(row['second_zone'])} {row['second_weight']:.2f}"
        ax.annotate(
            label, (centroid.x, centroid.y), ha="center", va="center", fontsize=annotation_fontsize, linespacing=0.9
        )

    handles = [mpatches.Patch(color=color_map[z], label=z) for z in zones]
    ax.legend(handles=handles, loc="lower left", frameon=False, fontsize=8, ncol=2)
    ax.set_title(f"{title} (n={len(zones)} zones, {len(boundary_cells)} multi-zone cells)")
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")
    fig.tight_layout()
    return fig, boundary_cells

# %% [markdown]
# ## PEON onshore zones
#
# Every 0.25-degree cell touched by one of the 7 German PEON zones, colored
# by its highest-weight zone. Annotated cells (small text) are the ones where
# a wind unit's capacity would actually be split — a cell with a second zone
# at nonzero weight.

# %%
peon_cells, peon_zones = zone_grid_cells(paths.peon_mask_file)
nuts2 = gpd.read_file(paths.nuts_regions_file)
germany_nuts2 = nuts2[nuts2["LEVL_CODE"] == 2]

fig, boundary_cells_peon = render_zone_map(
    peon_cells,
    peon_zones,
    "PEON onshore zones",
    draw_context=lambda ax: germany_nuts2.boundary.plot(ax=ax, color="#52514e", linewidth=0.4, zorder=3),
)
fig.savefig(paths.images_path / "08_peon_zone_grid.png", dpi=150, bbox_inches="tight")
plt.show()

print(f"PEON: {len(peon_cells):,} cells total, {len(boundary_cells_peon):,} multi-zone (boundary) cells")

# %% [markdown]
# ```{figure} ../../output/images/08_peon_zone_grid.png
# :name: fig-08-peon-zone-grid
# PECD v4.2 PEON onshore wind zones as raw 0.25-degree grid cells, colored by
# each cell's highest-weight zone (real NUTS2 boundaries in gray for context).
# Annotated cells carry nonzero weight from more than one zone — these are
# where `pipeline/07_build_wind_zone_panel.py` actually splits a wind unit's
# capacity across regions.
# ```

# %% [markdown]
# ## PEOF offshore zones
#
# Same idea for the 6 German PEOF zones (North Sea sub-zones `DE011_OFF`
# .. `DE015_OFF` plus `DE02_OFF` covering the whole Baltic Sea) — plotted
# against neighboring countries' coastlines rather than NUTS boundaries,
# since offshore has no NUTS region of its own.

# %%
peof_cells, peof_zones = zone_grid_cells(paths.peof_mask_file)
country_borders = gpd.read_file(paths.country_borders_file)

fig, boundary_cells_peof = render_zone_map(
    peof_cells,
    peof_zones,
    "PEOF offshore zones",
    draw_context=lambda ax: country_borders.plot(ax=ax, facecolor="#f2f0ea", edgecolor="#52514e", linewidth=0.5, zorder=1),
)
fig.savefig(paths.images_path / "08_peof_zone_grid.png", dpi=150, bbox_inches="tight")
plt.show()

print(f"PEOF: {len(peof_cells):,} cells total, {len(boundary_cells_peof):,} multi-zone (boundary) cells")

# %% [markdown]
# ```{figure} ../../output/images/08_peof_zone_grid.png
# :name: fig-08-peof-zone-grid
# PECD v4.2 PEOF offshore wind zones as raw 0.25-degree grid cells, colored by
# each cell's highest-weight zone, against neighboring countries' coastlines.
# ```
