"""Project paths configuration.

All paths are resolved relative to the project root, making scripts runnable
from any working directory. Add a @property for each new data file introduced
in the pipeline.
"""

from pathlib import Path


class ProjPaths:
    """Centralized project paths.

    The root is inferred from the location of this file (pkg/), so scripts
    run correctly regardless of the working directory they are invoked from.
    """

    def __init__(self):
        self._pkg_path = Path(__file__).resolve().parent  # pkg/
        self._project_path = self._pkg_path.parent        # project root

    # ------------------------------------------------------------------ #
    # Top-level directories                                                #
    # ------------------------------------------------------------------ #

    @property
    def project_path(self) -> Path:
        """Root project directory."""
        return self._project_path

    @property
    def pkg_path(self) -> Path:
        """Source package directory (pkg/)."""
        return self._pkg_path

    @property
    def pipeline_path(self) -> Path:
        """Pipeline scripts directory."""
        return self._project_path / "pipeline"

    # ------------------------------------------------------------------ #
    # Data directories                                                     #
    # ------------------------------------------------------------------ #

    @property
    def data_path(self) -> Path:
        """Main data directory."""
        return self._project_path / "data"

    @property
    def downloads_path(self) -> Path:
        """Raw downloaded data."""
        return self.data_path / "downloads"

    @property
    def processed_data_path(self) -> Path:
        """Processed/transformed data."""
        return self.data_path / "processed"

    # ------------------------------------------------------------------ #
    # Output directories                                                   #
    # ------------------------------------------------------------------ #

    @property
    def output_path(self) -> Path:
        """Generated outputs root."""
        return self._project_path / "output"

    @property
    def images_path(self) -> Path:
        """Chart/figure images saved by pipeline scripts."""
        return self.output_path / "images"

    @property
    def reports_path(self) -> Path:
        """Report files."""
        return self.output_path / "reports"

    # ------------------------------------------------------------------ #
    # MaStR data files                                                     #
    # ------------------------------------------------------------------ #

    @property
    def mastr_home_path(self) -> Path:
        """open-mastr's own working directory (SQLite DB, XML/doc cache)."""
        return self.downloads_path / "mastr_home"

    @property
    def mastr_units_raw_path(self) -> Path:
        """Raw MaStR units, one parquet file per technology (one row per unit).

        Kept as a directory of per-technology files rather than a single
        consolidated file: solar alone is several million rows, and writing
        (and later re-reading) one combined file repeatedly forced the whole
        dataset into memory at once, which OOM'd on this machine. Processing
        one technology's file at a time keeps peak memory bounded.
        """
        return self.downloads_path / "mastr_units_raw"

    # ------------------------------------------------------------------ #
    # NUTS region data files                                               #
    # ------------------------------------------------------------------ #

    @property
    def nuts_regions_file(self) -> Path:
        """Germany NUTS region geometries (all levels), from GISCO."""
        return self.downloads_path / "nuts_regions.geojson"

    @property
    def lau_nuts_correspondence_file(self) -> Path:
        """German municipality (AGS/LAU) -> NUTS3 code crosswalk, from Eurostat."""
        return self.downloads_path / "lau_nuts_correspondence.parquet"

    @property
    def country_borders_file(self) -> Path:
        """Country-level (LEVL_CODE 0) outlines for Germany + North/Baltic Sea neighbors.

        Used for map context around offshore wind areas, which sit outside
        any NUTS region. See `pipeline/02_download_nuts.py`.
        """
        return self.downloads_path / "country_borders.geojson"

    # ------------------------------------------------------------------ #
    # PECD wind zone mask files                                            #
    # ------------------------------------------------------------------ #

    @property
    def pecd_masks_path(self) -> Path:
        """Directory for PECD v4.2 region mask NetCDF files."""
        return self.downloads_path / "pecd"

    @property
    def peon_mask_file(self) -> Path:
        """PECD v4.2 PEON (pan-European onshore wind zone) region mask.

        Fractional (0-1) area coverage of each 0.25-degree grid cell by every
        European PEON zone; Germany intersects 7 (`DE01`..`DE07`). See
        `~/research/delu-headline-forecast/docs/data_sources.md` for background
        and `pipeline/06_download_pecd_masks.py`.
        """
        return self.pecd_masks_path / "peon_region_mask.nc"

    @property
    def peof_mask_file(self) -> Path:
        """PECD v4.2 PEOF (pan-European offshore wind zone) region mask.

        Same structure as `peon_mask_file`; Germany intersects 6 zones
        (`DE011_OFF`..`DE015_OFF`, `DE02_OFF`).
        """
        return self.pecd_masks_path / "peof_region_mask.nc"

    # ------------------------------------------------------------------ #
    # Processed data files                                                 #
    # ------------------------------------------------------------------ #

    @property
    def capacity_events_file(self) -> Path:
        """Unit-level capacity data with region assigned."""
        return self.processed_data_path / "capacity_events.parquet"

    @property
    def capacity_by_region_year_file(self) -> Path:
        """Annual installed-capacity snapshot panel, by region x technology x year."""
        return self.processed_data_path / "capacity_by_region_year.parquet"

    @property
    def capacity_by_region_year_pv_category_file(self) -> Path:
        """Annual solar-only panel split by behind-the-meter category (region x category x year).

        Category is one of: full_feed_in, self_consumption_with_storage,
        self_consumption_no_storage, unknown. See `pipeline/03_build_capacity_panel.py`.
        """
        return self.processed_data_path / "capacity_by_region_year_pv_category.parquet"

    @property
    def capacity_by_region_month_file(self) -> Path:
        """Monthly (end-of-month) export, by NUTS3 region x series x month, from 2015 on.

        `series` is one of: solar_full_feed_in, solar_self_consumption_no_storage,
        solar_self_consumption_with_storage, solar_unknown, storage, wind_onshore.
        For joining against weather data at region/month granularity. See
        `pipeline/03_build_capacity_panel.py`.
        """
        return self.processed_data_path / "capacity_by_region_month.parquet"

    @property
    def capacity_by_nuts2_month_file(self) -> Path:
        """Monthly (end-of-month) export, by NUTS2 region x series x month, from 2015 on.

        Same columns and `series` values as `capacity_by_region_month_file`
        (excluding `storage`, which has no NUTS2 breakdown), aggregated up from
        NUTS3 to NUTS2 by truncating the NUTS3 code to its first 4 characters.
        See `pipeline/03_build_capacity_panel.py`.
        """
        return self.processed_data_path / "capacity_by_nuts2_month.parquet"

    @property
    def capacity_by_peon_month_file(self) -> Path:
        """Monthly (end-of-month) onshore wind export, by PEON zone x month, from 2015 on.

        Same shape as `capacity_by_region_month_file`'s `wind_onshore` slice,
        but keyed by PEON zone (`DE01`..`DE07`) instead of NUTS3 region. Each
        wind unit's capacity is fractionally split across every PEON zone
        with nonzero coverage at the unit's grid cell, instead of being
        assigned to one region — so `unit_count` here is a fractional sum,
        not an integer count. See `pipeline/07_build_wind_zone_panel.py`.
        """
        return self.processed_data_path / "capacity_by_peon_month.parquet"

    @property
    def capacity_by_peof_month_file(self) -> Path:
        """Monthly (end-of-month) offshore wind export, by PEOF zone x month, from 2015 on.

        Same idea as `capacity_by_peon_month_file`, for offshore wind, keyed
        by PEOF zone (`DE011_OFF`..`DE015_OFF`, `DE02_OFF`) instead of MaStR's
        two North Sea/Baltic Sea pseudo-regions.
        """
        return self.processed_data_path / "capacity_by_peof_month.parquet"

    @property
    def capacity_by_offshore_month_file(self) -> Path:
        """Monthly (end-of-month) export for offshore wind, by the two offshore
        pseudo-regions (DEZZ-NORDSEE / DEZZ-OSTSEE) x month, from 2015 on.
        """
        return self.processed_data_path / "capacity_by_offshore_month.parquet"

    @property
    def offshore_regions_file(self) -> Path:
        """Offshore wind footprint polygons (North Sea / Baltic Sea), as GeoJSON.

        One polygon per cluster: the convex hull of every currently-installed
        offshore turbine's coordinates. Built once here (not in the EDA
        notebook) so the hull-construction logic exists in exactly one place.
        """
        return self.processed_data_path / "offshore_regions.geojson"

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def ensure_directories(self) -> None:
        """Create all standard directories if they do not yet exist."""
        dirs = [
            self.downloads_path,
            self.processed_data_path,
            self.images_path,
            self.reports_path,
            self.mastr_home_path,
            self.mastr_units_raw_path,
            self.pecd_masks_path,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
