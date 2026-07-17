"""Shared monthly-snapshot-panel builder, used by pipeline/03_build_capacity_panel.py
and pipeline/07_build_wind_zone_panel.py.
"""

import pandas as pd


def monthly_snapshot_panel(
    df: pd.DataFrame,
    group_cols: list[str],
    month_range: pd.PeriodIndex,
    export_start_period: pd.Period,
    capacity_col: str = "capacity_mw",
    weight_col: str | None = None,
) -> pd.DataFrame:
    """Installed capacity + unit count per group, for every month in `month_range`.

    Vectorized cumulative-delta approach: adds +capacity at a unit's
    commissioning month and -capacity at its shutdown month (if any), then
    takes a cumulative sum along the month axis per group — a unit
    contributes to every month from commissioning up to (excluding) its
    shutdown month. This turns "N passes over the whole table, one per
    month" into a handful of groupby/cumsum calls over a much smaller
    (group x month) grid.

    `capacity_col` defaults to `"capacity_mw"`, but a caller can pass in a
    pre-weighted column (e.g. a unit's capacity scaled by its fractional
    membership in one of several groups it's split across). `weight_col`,
    if given, is used as the per-row contribution to `unit_count` in place of
    the default 1-per-row — for the same fractional-split case, so
    `unit_count` sums to the true unit count across a unit's split rows
    rather than double-counting it once per group.
    """
    start_period = df["commissioning_date"].dt.to_period("M")
    end_period = df["final_shutdown_date"].dt.to_period("M")
    has_end = end_period.notna()
    weight = df[weight_col] if weight_col is not None else 1

    adds = df[group_cols].copy()
    adds["period"] = start_period
    adds["capacity_delta"] = df[capacity_col]
    adds["count_delta"] = weight

    removes = df.loc[has_end, group_cols].copy()
    removes["period"] = end_period[has_end]
    removes["capacity_delta"] = -df.loc[has_end, capacity_col]
    removes["count_delta"] = -(weight[has_end] if weight_col is not None else 1)

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
        net["count_delta"].unstack("period").reindex(columns=month_range, fill_value=0.0)
        .fillna(0.0).cumsum(axis=1)
    )

    panel = pd.concat(
        [capacity.stack().rename("capacity_mw"), unit_count.stack().rename("unit_count")], axis=1
    ).reset_index()
    panel = panel.rename(columns={"period": "month"})
    panel = panel[panel["month"] >= export_start_period].copy()
    panel["month"] = panel["month"].dt.to_timestamp() + pd.offsets.MonthEnd(0)
    return panel.reset_index(drop=True)
