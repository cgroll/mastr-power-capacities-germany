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
# # Exploratory Data Analysis: German Installed Power Capacities
#
# This notebook explores the MaStR (Marktstammdatenregister) dataset of
# renewable generation and storage units in Germany:
# - overview statistics on the raw unit-level data
# - how installed solar/wind capacity, and battery storage, have grown over time
# - where solar and wind capacity is located across German NUTS3 regions
# - an animated map of solar & wind capacity growth, year by year

# %%
import io

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from PIL import Image
from mpg.paths import ProjPaths

paths = ProjPaths()
paths.ensure_directories()

events = pd.read_parquet(paths.capacity_events_file)
panel = pd.read_parquet(paths.capacity_by_region_year_file)
regions = gpd.read_file(paths.nuts_regions_file)

TECHNOLOGY_ORDER = ["wind", "solar", "biomass", "hydro", "gsgk", "storage"]
TECHNOLOGY_COLORS = {
    "wind": "#1B7A9C",
    "solar": "#E8A33D",
    "biomass": "#4C9A5A",
    "hydro": "#3355B0",
    "gsgk": "#8A5FBF",
    "storage": "#B0472E",
}

# Solar and wind only really take off from ~1990 onward; the full history back
# to 1900 is dominated by a handful of very old hydro plants (some carrying a
# "1900-01-01" placeholder commissioning date rather than a real one) and just
# stretches the time axis without showing anything.
CHART_START_YEAR = 1990

# %% [markdown]
# ## Overview

# %%
print(f"Units: {len(events):,}")
print(f"Total installed capacity: {events['capacity_mw'].sum():,.0f} MW")
print(
    "Commissioning dates: "
    f"{events['commissioning_date'].min().date()} - {events['commissioning_date'].max().date()}"
)
print("\nUnits and capacity by technology:")
print(
    events.groupby("technology")
    .agg(units=("unit_id", "count"), capacity_mw=("capacity_mw", "sum"))
    .reindex(TECHNOLOGY_ORDER)
    .round(0)
)

# %% [markdown]
# ## Solar & wind installed capacity over time
#
# National total installed capacity at the end of each year, based on
# commissioning and final-shutdown dates (fixed current NUTS3 boundaries;
# only the capacity mix changes across years, see `pipeline/03_build_capacity_panel.py`).

# %%
SOLAR_WIND = ["wind", "solar"]

national = (
    panel.groupby(["year", "technology"])["capacity_mw"].sum().unstack("technology")
)
national = national.reindex(columns=SOLAR_WIND, fill_value=0.0)
national = national[national.index >= CHART_START_YEAR]

fig, ax = plt.subplots(figsize=(12, 5))
ax.stackplot(
    national.index,
    [national[tech] for tech in SOLAR_WIND],
    labels=SOLAR_WIND,
    colors=[TECHNOLOGY_COLORS[tech] for tech in SOLAR_WIND],
)
ax.set_xlabel("Year")
ax.set_ylabel("Installed capacity (MW)")
ax.set_title("Germany: installed solar + wind capacity")
ax.legend(loc="upper left", frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(paths.images_path / "04_solar_wind_capacity_over_time.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/04_solar_wind_capacity_over_time.png
# :name: fig-04-solar-wind-over-time
# National installed solar + wind capacity, year-end snapshots.
# ```

# %% [markdown]
# ## Battery storage installed capacity over time

# %%
storage_national = panel[panel["technology"] == "storage"].groupby("year")["capacity_mw"].sum()
storage_national = storage_national[storage_national.index >= CHART_START_YEAR]

fig, ax = plt.subplots(figsize=(12, 4))
ax.fill_between(storage_national.index, storage_national.values, color=TECHNOLOGY_COLORS["storage"], alpha=0.85)
ax.set_xlabel("Year")
ax.set_ylabel("Installed capacity (MW)")
ax.set_title("Germany: installed battery storage capacity")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(paths.images_path / "04_storage_capacity_over_time.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/04_storage_capacity_over_time.png
# :name: fig-04-storage-over-time
# National installed battery storage capacity, year-end snapshots.
# ```

# %% [markdown]
# ## Where is solar capacity installed? (latest snapshot)

# %%
latest_year = panel["year"].max()
latest = panel[panel["year"] == latest_year]

nuts3 = regions[regions["LEVL_CODE"] == 3].copy()

solar_by_region = latest[latest["technology"] == "solar"].groupby("region_code")["capacity_mw"].sum()
nuts3["solar_capacity_mw"] = nuts3["NUTS_ID"].map(solar_by_region).fillna(0.0)

fig, ax = plt.subplots(figsize=(8, 9))
nuts3.plot(
    column="solar_capacity_mw",
    cmap="Oranges",
    linewidth=0.2,
    edgecolor="white",
    legend=True,
    legend_kwds={"label": "Installed capacity (MW)", "shrink": 0.6},
    ax=ax,
)
ax.set_title(f"Solar installed capacity by NUTS3 region ({latest_year})")
ax.axis("off")
fig.tight_layout()
fig.savefig(paths.images_path / "04_capacity_map_solar.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/04_capacity_map_solar.png
# :name: fig-04-capacity-map-solar
# Solar installed capacity by NUTS3 region as of the latest year-end snapshot.
# ```

# %% [markdown]
# ## Where is wind capacity installed? (latest snapshot)
#
# Onshore wind is mapped by NUTS3 region. Offshore wind has no NUTS3 region of
# its own, and its per-cluster capacity (North Sea / Baltic Sea) is an order of
# magnitude larger than any single onshore region — putting it on the same
# color scale as the choropleth washes out all onshore detail, so it's shown
# as a separate bar chart instead.

# %%
wind_by_region = latest[
    (latest["technology"] == "wind") & (~latest["region_code"].str.startswith("DEZZ"))
].groupby("region_code")["capacity_mw"].sum()
nuts3["wind_capacity_mw"] = nuts3["NUTS_ID"].map(wind_by_region).fillna(0.0)

offshore = latest[
    (latest["technology"] == "wind") & latest["region_code"].str.startswith("DEZZ")
].groupby("region_code")["capacity_mw"].sum()

fig, axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [4, 1]})

nuts3.plot(
    column="wind_capacity_mw",
    cmap="Blues",
    linewidth=0.2,
    edgecolor="white",
    legend=True,
    legend_kwds={"label": "Installed capacity (MW)", "shrink": 0.6},
    ax=axes[0],
)
axes[0].set_title(f"Onshore wind by NUTS3 region ({latest_year})")
axes[0].axis("off")

axes[1].bar(offshore.index.str.replace("DEZZ-", ""), offshore.values, color=TECHNOLOGY_COLORS["wind"])
axes[1].set_title("Offshore wind")
axes[1].set_ylabel("Installed capacity (MW)")
axes[1].spines[["top", "right"]].set_visible(False)

fig.tight_layout()
fig.savefig(paths.images_path / "04_capacity_map_wind.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/04_capacity_map_wind.png
# :name: fig-04-capacity-map-wind
# Onshore wind installed capacity by NUTS3 region as of the latest year-end
# snapshot, with offshore wind (North Sea / Baltic Sea) shown separately.
# ```

# %% [markdown]
# ## Offshore wind footprints
#
# Germany's offshore wind clusters (North Sea / Baltic Sea) have no NUTS
# region of their own. Instead of a single representative point, this plots
# an actual footprint polygon per cluster — the convex hull of every
# currently-installed offshore turbine's real coordinates, built once in
# `pipeline/03_build_capacity_panel.py` (and exported for reuse rather than
# recomputed here) — against neighboring countries' coastlines for context.

# %%
country_borders = gpd.read_file(paths.country_borders_file)
offshore_regions = gpd.read_file(paths.offshore_regions_file)
snapshot_date = pd.Timestamp(year=latest_year, month=12, day=31)

offshore_units = events[
    (events["technology"] == "wind")
    & events["region_code"].str.startswith("DEZZ")
    & (events["commissioning_date"] <= snapshot_date)
    & (events["final_shutdown_date"].isna() | (events["final_shutdown_date"] > snapshot_date))
].dropna(subset=["longitude", "latitude"])

OFFSHORE_COLORS = {"DEZZ-NORDSEE": "#1B7A9C", "DEZZ-OSTSEE": "#8B4A1E"}

fig, ax = plt.subplots(figsize=(9, 9))
country_borders.plot(ax=ax, facecolor="#eeeeee", edgecolor="#999999", linewidth=0.8)
nuts3.boundary.plot(ax=ax, color="#cccccc", linewidth=0.3)
for _, row in offshore_regions.iterrows():
    gpd.GeoSeries([row["geometry"]], crs="EPSG:4326").plot(
        ax=ax, color=OFFSHORE_COLORS[row["region_code"]], alpha=0.45, edgecolor="black", linewidth=1.2
    )
    centroid = row["geometry"].centroid
    ax.annotate(
        f"{row['region_code'].replace('DEZZ-', '').title()}\n"
        f"{row['capacity_mw']:,.0f} MW ({row['turbine_count']:,} turbines)",
        (centroid.x, centroid.y),
        ha="center",
        fontsize=9,
        fontweight="bold",
    )
ax.scatter(offshore_units["longitude"], offshore_units["latitude"], s=4, color="black", alpha=0.4, zorder=5)
ax.set_xlim(3, 20)
ax.set_ylim(51, 57)
ax.set_title(f"Offshore wind footprint ({latest_year})")
ax.axis("off")
fig.tight_layout()
fig.savefig(paths.images_path / "04_offshore_regions_map.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/04_offshore_regions_map.png
# :name: fig-04-offshore-regions-map
# Offshore wind footprint polygons (convex hull of turbine coordinates) for
# the North Sea and Baltic Sea clusters, with individual turbines (dots) and
# neighboring countries' coastlines for context.
# ```

# %% [markdown]
# ## Solar & wind installed capacity, year by year
#
# Animated end-of-year snapshots from 1990 to the latest year, one frame per
# year. Each technology uses a fixed color scale
# (0 to that technology's all-time regional maximum) across every frame, so
# color darkening over time reflects real growth rather than a rescaled axis.

# %%
solar_pivot = (
    panel[panel["technology"] == "solar"]
    .pivot_table(index="region_code", columns="year", values="capacity_mw", fill_value=0.0)
)
wind_pivot = (
    panel[(panel["technology"] == "wind") & (~panel["region_code"].str.startswith("DEZZ"))]
    .pivot_table(index="region_code", columns="year", values="capacity_mw", fill_value=0.0)
)

anim_years = [y for y in range(CHART_START_YEAR, latest_year + 1) if y in solar_pivot.columns]
solar_vmax = solar_pivot.loc[:, anim_years].values.max()
wind_vmax = wind_pivot.loc[:, anim_years].values.max()

frames = []
for year in anim_years:
    nuts3["solar_frame"] = nuts3["NUTS_ID"].map(solar_pivot[year]).fillna(0.0)
    nuts3["wind_frame"] = nuts3["NUTS_ID"].map(wind_pivot[year]).fillna(0.0)

    fig, axes = plt.subplots(1, 2, figsize=(11, 6.5))
    nuts3.plot(column="solar_frame", cmap="Oranges", vmin=0, vmax=solar_vmax, linewidth=0.1, edgecolor="white", legend=True, legend_kwds={"shrink": 0.5}, ax=axes[0])
    nuts3.plot(column="wind_frame", cmap="Blues", vmin=0, vmax=wind_vmax, linewidth=0.1, edgecolor="white", legend=True, legend_kwds={"shrink": 0.5}, ax=axes[1])
    axes[0].set_title("Solar")
    axes[1].set_title("Wind (onshore)")
    for ax in axes:
        ax.axis("off")
    fig.suptitle(f"Installed capacity — end of {year}")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    frames.append(Image.open(buf).convert("RGB"))

gif_path = paths.images_path / "04_capacity_map_animation.gif"
frames[0].save(
    gif_path, save_all=True, append_images=frames[1:], duration=350, loop=0
)
print(f"Saved {len(frames)}-frame animation -> {gif_path}")

# %% [markdown]
# ```{figure} ../../output/images/04_capacity_map_animation.gif
# :name: fig-04-capacity-map-animation
# Solar and onshore wind installed capacity by NUTS3 region, animated
# end-of-year snapshots.
# ```

# %% [markdown]
# ## Behind-the-meter PV: grid-direct vs. self-consumption vs. self-consumption+storage
#
# For grid-level demand/generation modeling, what matters isn't just how much
# solar capacity exists, but how much of it feeds straight into the grid vs.
# is consumed behind the meter first. Each solar unit is classified using
# MaStR's `feed_in_type` field plus a location-based join against storage
# units — see `pipeline/03_build_capacity_panel.py` for the full methodology
# and why simpler approaches (a same-location flag MaStR itself provides, and
# storage's own "co-registered solar unit" field) don't work well here.

# %%
pv_panel = pd.read_parquet(paths.capacity_by_region_year_pv_category_file)

PV_CATEGORY_ORDER = ["full_feed_in", "self_consumption_no_storage", "self_consumption_with_storage"]
PV_CATEGORY_LABELS = {
    "full_feed_in": "Full grid feed-in",
    "self_consumption_no_storage": "Self-consumption (no storage)",
    "self_consumption_with_storage": "Self-consumption + storage",
}
PV_CATEGORY_COLORS = {
    "full_feed_in": "#E8A33D",
    "self_consumption_no_storage": "#C97A2B",
    "self_consumption_with_storage": "#8B4A1E",
}

# %% [markdown]
# ### Over time

# %%
pv_known = pv_panel[pv_panel["pv_category"] != "unknown"]
pv_national = pv_known.groupby(["year", "pv_category"])["capacity_mw"].sum().unstack("pv_category")
pv_national = pv_national.reindex(columns=PV_CATEGORY_ORDER, fill_value=0.0)
pv_national = pv_national[pv_national.index >= CHART_START_YEAR]

fig, ax = plt.subplots(figsize=(12, 5))
ax.stackplot(
    pv_national.index,
    [pv_national[cat] for cat in PV_CATEGORY_ORDER],
    labels=[PV_CATEGORY_LABELS[cat] for cat in PV_CATEGORY_ORDER],
    colors=[PV_CATEGORY_COLORS[cat] for cat in PV_CATEGORY_ORDER],
)
ax.set_xlabel("Year")
ax.set_ylabel("Installed capacity (MW)")
ax.set_title("Germany: solar capacity by behind-the-meter category")
ax.legend(loc="upper left", frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(paths.images_path / "04_pv_category_over_time.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/04_pv_category_over_time.png
# :name: fig-04-pv-category-over-time
# National solar capacity by behind-the-meter category, year-end snapshots.
# ```

# %% [markdown]
# ### Is the mix similar across Germany?
#
# Share of each category within each state's total solar capacity, latest
# snapshot. If the bars look similar across states, the national split above
# is a reasonable stand-in per region for grid modeling; if a state stands
# out, it needs its own mix rather than the national average.

# %%
nuts1_names = regions.loc[regions["LEVL_CODE"] == 1].set_index("NUTS_ID")["NUTS_NAME"]

pv_latest_onshore = pv_known[
    (pv_known["year"] == latest_year) & (~pv_known["region_code"].str.startswith("DEZZ"))
].copy()
pv_latest_onshore["state"] = pv_latest_onshore["region_code"].str[:3].map(nuts1_names)

by_state = (
    pv_latest_onshore.groupby(["state", "pv_category"])["capacity_mw"]
    .sum()
    .unstack("pv_category")
    .reindex(columns=PV_CATEGORY_ORDER, fill_value=0.0)
)
by_state_share = by_state.div(by_state.sum(axis=1), axis=0).sort_values("full_feed_in")

fig, ax = plt.subplots(figsize=(10, 7))
left = pd.Series(0.0, index=by_state_share.index)
for cat in PV_CATEGORY_ORDER:
    ax.barh(by_state_share.index, by_state_share[cat], left=left, color=PV_CATEGORY_COLORS[cat], label=PV_CATEGORY_LABELS[cat])
    left = left + by_state_share[cat]
ax.set_xlabel("Share of solar capacity")
ax.set_title(f"Behind-the-meter PV mix by state ({latest_year})")
ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3, frameon=False)
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(paths.images_path / "04_pv_category_by_state.png", dpi=150, bbox_inches="tight")
plt.show()

print("Spread across states (max - min share, by category):")
print((by_state_share.max() - by_state_share.min()).round(3))

# %% [markdown]
# ```{figure} ../../output/images/04_pv_category_by_state.png
# :name: fig-04-pv-category-by-state
# Behind-the-meter PV mix as a share of each state's solar capacity, latest
# year-end snapshot.
# ```

# %% [markdown]
# ### Plant size distribution by category
#
# Expectation: household PV is small and mostly self-consumption, so
# full-feed-in should skew toward much larger plants than either
# self-consumption category.

# %%
solar_known = events[(events["technology"] == "solar") & (events["pv_category"] != "unknown")].copy()
solar_known["capacity_kw"] = solar_known["capacity_mw"] * 1000.0

print("Capacity per unit (kW) by category:")
print(
    solar_known.groupby("pv_category")["capacity_kw"]
    .describe(percentiles=[0.25, 0.5, 0.75, 0.9])
    .reindex(PV_CATEGORY_ORDER)
    .round(1)
)

fig, ax = plt.subplots(figsize=(9, 5))
box_data = [solar_known.loc[solar_known["pv_category"] == cat, "capacity_kw"] for cat in PV_CATEGORY_ORDER]
bp = ax.boxplot(
    box_data,
    vert=False,
    showfliers=False,
    patch_artist=True,
    tick_labels=[PV_CATEGORY_LABELS[cat] for cat in PV_CATEGORY_ORDER],
)
for patch, cat in zip(bp["boxes"], PV_CATEGORY_ORDER):
    patch.set_facecolor(PV_CATEGORY_COLORS[cat])
ax.set_xscale("log")
ax.set_xlabel("Capacity per unit (kW, log scale)")
ax.set_title("Plant size distribution by behind-the-meter category")
ax.spines[["top", "right"]].set_visible(False)
fig.tight_layout()
fig.savefig(paths.images_path / "04_pv_category_size_distribution.png", dpi=150, bbox_inches="tight")
plt.show()

# %% [markdown]
# ```{figure} ../../output/images/04_pv_category_size_distribution.png
# :name: fig-04-pv-category-size-distribution
# Distribution of installed capacity per unit (kW, log scale) by
# behind-the-meter category. Box = IQR, whiskers = 1.5x IQR, outliers hidden
# (millions of units would otherwise cover the plot).
# ```

# %% [markdown]
# ### Cross-check against usage sector and installation type
#
# Two independent MaStR fields not used in the classification itself —
# `usage_sector` (household/commercial/industrial/agricultural) and
# `installation_type` (rooftop/balcony/ground-mounted) — should still line up
# with it: full-feed-in should skew toward ground-mounted/commercial-industrial,
# self-consumption toward household rooftop. This is a sanity check on the
# classification, not a new category.

# %%
SUB_CATEGORY_COLORS = plt.get_cmap("tab10").colors


def pv_category_composition_chart(group_col, title, filename):
    share = (
        solar_known.groupby(["pv_category", group_col], observed=True)["capacity_mw"]
        .sum()
        .unstack(group_col)
        .reindex(PV_CATEGORY_ORDER)
    )
    share = share.div(share.sum(axis=1), axis=0)
    share = share[share.sum().sort_values(ascending=False).index]  # largest sub-category first

    fig, ax = plt.subplots(figsize=(9, 4.5))
    bar_labels = [PV_CATEGORY_LABELS[cat] for cat in share.index]
    left = pd.Series(0.0, index=share.index)
    for i, col in enumerate(share.columns):
        ax.barh(bar_labels, share[col], left=left, color=SUB_CATEGORY_COLORS[i % len(SUB_CATEGORY_COLORS)], label=col)
        left = left + share[col]
    ax.set_xlabel("Share of capacity")
    ax.set_title(title)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=2, frameon=False, fontsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(paths.images_path / filename, dpi=150, bbox_inches="tight")
    plt.show()


pv_category_composition_chart(
    "usage_sector", "PV category composition by usage sector", "04_pv_category_usage_sector.png"
)
pv_category_composition_chart(
    "installation_type", "PV category composition by installation type", "04_pv_category_installation_type.png"
)

# %% [markdown]
# ```{figure} ../../output/images/04_pv_category_usage_sector.png
# :name: fig-04-pv-category-usage-sector
# Usage-sector composition of each behind-the-meter PV category.
# ```
#
# ```{figure} ../../output/images/04_pv_category_installation_type.png
# :name: fig-04-pv-category-installation-type
# Installation-type composition of each behind-the-meter PV category.
# ```

# %% [markdown]
# ## Comparison against official Bundesnetzagentur / SMARD figures
#
# The Bundesnetzagentur publishes official year-end installed-capacity
# figures via [SMARD](https://www.smard.de/page/en/wiki-article/5884/6038/installed-generation-capacity)
# and its [press release on 2025 renewables growth](https://www.bundesnetzagentur.de/SharedDocs/Pressemitteilungen/EN/2026/20260108_EEG.html).
# Comparing our end-of-2025 snapshot (not the still-incomplete current year)
# against those official end-of-2025 figures is a useful sanity check on the
# MaStR-derived numbers above.

# %%
OFFICIAL_END_2025_MW = {
    "solar": 117_000,
    "wind_onshore": 68_100,
    "wind_offshore": 9_500,
    "biomass": 9_200,
}

p2025 = panel[panel["year"] == 2025]
is_offshore = p2025["region_code"].str.startswith("DEZZ")
mastr_end_2025_mw = {
    "solar": p2025.loc[p2025["technology"] == "solar", "capacity_mw"].sum(),
    "wind_onshore": p2025.loc[(p2025["technology"] == "wind") & ~is_offshore, "capacity_mw"].sum(),
    "wind_offshore": p2025.loc[(p2025["technology"] == "wind") & is_offshore, "capacity_mw"].sum(),
    "biomass": p2025.loc[p2025["technology"] == "biomass", "capacity_mw"].sum(),
}

comparison = pd.DataFrame({"mastr_mw": mastr_end_2025_mw, "official_mw": OFFICIAL_END_2025_MW})
comparison["diff_mw"] = comparison["mastr_mw"] - comparison["official_mw"]
comparison["diff_pct"] = 100 * comparison["diff_mw"] / comparison["official_mw"]
print(comparison.round(1))

# %% [markdown]
# Onshore and offshore wind match the official figures closely (within ~1-3%).
# Solar comes in noticeably below the official number — a known characteristic
# of MaStR rather than a pipeline bug: it's a self-reported registry, and small
# rooftop PV systems in particular are often registered with a lag of months,
# so the most recent year is always undercounted until later backfilling
# catches up (see the [open-mastr data quality paper](https://doi.org/10.1145/3717413.3717421)
# referenced in its docs).
