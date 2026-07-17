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
# # Region Granularity: NUTS3 vs. NUTS2
#
# The EDA notebook maps installed capacity at NUTS3 resolution — Germany's
# ~400 districts (Kreise/kreisfreie Städte). This notebook is a quick visual
# comparison against the coarser NUTS2 level (~38 regions), to help judge
# whether NUTS3 detail is worth keeping for downstream modeling or whether
# NUTS2 would be a reasonable simplification.
#
# Both maps also overlay the DE-LU day-ahead electricity bidding zone —
# Germany and Luxembourg's single merged market area — for scale: it's the
# outer boundary either NUTS level ultimately rolls up to for grid/market
# modeling.

# %%
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from mpg.paths import ProjPaths
from shapely.ops import unary_union

paths = ProjPaths()
paths.ensure_directories()

regions = gpd.read_file(paths.nuts_regions_file)
country_borders = gpd.read_file(paths.country_borders_file)

nuts3 = regions[regions["LEVL_CODE"] == 3]
nuts2 = regions[regions["LEVL_CODE"] == 2]

# DE-LU bidding zone == Germany + Luxembourg unioned (Luxembourg has no TSO of
# its own; the two have shared a single day-ahead bidding zone since Oct 2018).
de_lu = country_borders[country_borders["CNTR_CODE"].isin(["DE", "LU"])]
de_lu_boundary = gpd.GeoSeries([unary_union(de_lu.geometry)], crs=de_lu.crs)
BIDDING_ZONE_COLOR = "#B0472E"
bidding_zone_legend = [
    Line2D([0], [0], color=BIDDING_ZONE_COLOR, linewidth=1.5, label="DE-LU bidding zone")
]

print(f"NUTS3 regions: {len(nuts3):,}")
print(f"NUTS2 regions: {len(nuts2):,}")
print(f"NUTS3 has {len(nuts3) / len(nuts2):.1f}x as many regions as NUTS2")

# %% [markdown]
# ## NUTS3 regions (districts)

# %%
fig, ax = plt.subplots(figsize=(7, 8))
nuts3.plot(ax=ax, facecolor="#CFE3F2", edgecolor="#1B7A9C", linewidth=0.3)
de_lu_boundary.boundary.plot(ax=ax, color=BIDDING_ZONE_COLOR, linewidth=1.5, zorder=5)
ax.set_title(f"Germany: NUTS3 regions (n={len(nuts3)})")
ax.axis("off")
ax.legend(handles=bidding_zone_legend, loc="lower left", frameon=False)
fig.tight_layout()
fig.savefig(paths.images_path / "05_nuts3_regions_map.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/05_nuts3_regions_map.png
# :name: fig-05-nuts3-regions-map
# Germany's NUTS3 regions (districts / Kreise), with the DE-LU bidding zone
# boundary overlaid.
# ```

# %% [markdown]
# ## NUTS2 regions

# %%
fig, ax = plt.subplots(figsize=(7, 8))
nuts2.plot(ax=ax, facecolor="#F2DFC2", edgecolor="#C97A2B", linewidth=0.6)
de_lu_boundary.boundary.plot(ax=ax, color=BIDDING_ZONE_COLOR, linewidth=1.5, zorder=5)
ax.set_title(f"Germany: NUTS2 regions (n={len(nuts2)})")
ax.axis("off")
ax.legend(handles=bidding_zone_legend, loc="lower left", frameon=False)
fig.tight_layout()
fig.savefig(paths.images_path / "05_nuts2_regions_map.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/05_nuts2_regions_map.png
# :name: fig-05-nuts2-regions-map
# Germany's NUTS2 regions — the coarser alternative to NUTS3 — with the DE-LU
# bidding zone boundary overlaid.
# ```
