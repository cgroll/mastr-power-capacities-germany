"""PECD/ERA5 0.25-degree grid geometry helpers.

Used by pipeline/07_build_wind_zone_panel.py (snap a unit to its nearest
cell, then read that cell's PEON/PEOF zone-membership fractions) and
pipeline/09_build_wind_grid_cell_panel.py (snap a unit to its nearest cell
and stop there — no zone step at all).
"""

import numpy as np


def nearest_grid_index(values: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Index of the nearest point in a regularly-spaced 1-D `grid` for each of `values`."""
    step = grid[1] - grid[0]
    idx = np.rint((values - grid[0]) / step).astype(int)
    return np.clip(idx, 0, len(grid) - 1)
