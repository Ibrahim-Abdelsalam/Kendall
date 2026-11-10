"""Central configuration schema for all Earth-science variables in Plot Twist.

Defines metadata, data source references, temporal windows, and regridding/aggregation
functions for all project variables.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional
import yaml


@dataclass
class VariableConfig:
    id: str
    name: str
    student_definition: str
    units: str
    dataset_short_name: str
    version: str
    source_variable: str
    source_group: Optional[str]
    file_format: str
    time_range: tuple[str, str]
    aggregation: str
    native_resolution: str
    is_flux_rate: bool = False
    scale_factor: float = 1.0
    add_offset: float = 0.0


VARIABLES: Dict[str, VariableConfig] = {
    "gpm_precip": VariableConfig(
        id="gpm_precip",
        name="Precipitation (GPM IMERG)",
        student_definition="The total liquid and frozen water that falls from the atmosphere to Earth's surface during a month.",
        units="mm/month",
        dataset_short_name="GPM_3IMERGM",
        version="07",
        source_variable="precipitation",
        source_group="Grid",
        file_format="HDF5",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="hours_per_month_integral",
        native_resolution="0.1 degree (1800 x 3600)",
        is_flux_rate=True,  # raw mm/hr -> mm/month
    ),
    "gldas_precip": VariableConfig(
        id="gldas_precip",
        name="Precipitation (GLDAS Reanalysis)",
        student_definition="Monthly rainfall and snowfall arriving at land surface modeled by atmospheric reanalysis (independent check).",
        units="mm/month",
        dataset_short_name="GLDAS_NOAH025_M",
        version="2.1",
        source_variable="Rainf_f_tavg",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="kg_m2_s_to_mm_month",
        native_resolution="0.25 degree (600 x 1440)",
        is_flux_rate=True,  # kg/m^2/s (= mm/s) * 86400 * days
    ),
    "gldas_soil_moist": VariableConfig(
        id="gldas_soil_moist",
        name="Top-Layer Soil Moisture (0-10cm)",
        student_definition="The amount of liquid water stored in the upper 10 cm of the soil column available to plant root systems.",
        units="kg/m^2",
        dataset_short_name="GLDAS_NOAH025_M",
        version="2.1",
        source_variable="SoilMoi0_10cm_inst",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="monthly_mean",
        native_resolution="0.25 degree (600 x 1440)",
    ),
    "gldas_temp": VariableConfig(
        id="gldas_temp",
        name="2m Air Temperature",
        student_definition="The temperature of ambient air measured 2 meters above the ground surface.",
        units="degC",
        dataset_short_name="GLDAS_NOAH025_M",
        version="2.1",
        source_variable="Tair_f_inst",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="kelvin_to_celsius",
        native_resolution="0.25 degree (600 x 1440)",
        add_offset=-273.15,
    ),
    "gldas_evap": VariableConfig(
        id="gldas_evap",
        name="Total Evapotranspiration",
        student_definition="The combined transfer of water to the atmosphere through evaporation from soil and transpiration from plants.",
        units="mm/month",
        dataset_short_name="GLDAS_NOAH025_M",
        version="2.1",
        source_variable="Evap_tavg",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="kg_m2_s_to_mm_month",
        native_resolution="0.25 degree (600 x 1440)",
        is_flux_rate=True,
    ),
    "merra2_aod": VariableConfig(
        id="merra2_aod",
        name="Aerosol Optical Depth (550nm)",
        student_definition="A dimensionless index of sunlight extinction by airborne atmospheric particles including smoke, dust, and haze.",
        units="1",
        dataset_short_name="M2TMNXAER",
        version="5.12.4",
        source_variable="TOTEXTTAU",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="monthly_mean",
        native_resolution="0.5 x 0.625 degree (361 x 576)",
    ),
    "gldas_swe": VariableConfig(
        id="gldas_swe",
        name="Snow Water Equivalent (GLDAS)",
        student_definition="The liquid water depth that would result from immediately melting the accumulated snowpack.",
        units="kg/m^2",
        dataset_short_name="GLDAS_NOAH025_M",
        version="2.1",
        source_variable="SWE_inst",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="monthly_mean",
        native_resolution="0.25 degree (600 x 1440)",
    ),
    "gldas_snow_depth": VariableConfig(
        id="gldas_snow_depth",
        name="Snow Depth (GLDAS)",
        student_definition="The physical vertical thickness of snow accumulation covering the ground surface.",
        units="m",
        dataset_short_name="GLDAS_NOAH025_M",
        version="2.1",
        source_variable="SnowDepth_inst",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="monthly_mean",
        native_resolution="0.25 degree (600 x 1440)",
    ),
    "merra2_ts": VariableConfig(
        id="merra2_ts",
        name="Surface temperature (land skin + ocean surface, MERRA-2)",
        student_definition="Thermodynamic skin temperature over land and prescribed sea surface temperature (SST) over ocean.",
        units="degC",
        dataset_short_name="M2TMNXSLV",
        version="5.12.4",
        source_variable="TS",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="kelvin_to_celsius",
        native_resolution="0.5 x 0.625 degree (361 x 576)",
        add_offset=-273.15,
    ),
    "merra2_wind": VariableConfig(
        id="merra2_wind",
        name="10m Wind Speed (MERRA-2)",
        student_definition="The magnitude of surface wind velocity at 10 meters above surface derived from eastward and northward vectors.",
        units="m/s",
        dataset_short_name="M2TMNXSLV",
        version="5.12.4",
        source_variable="WIND10M",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="monthly_mean",
        native_resolution="0.5 x 0.625 degree (361 x 576)",
    ),
    "merra2_ps": VariableConfig(
        id="merra2_ps",
        name="Surface Pressure (MERRA-2)",
        student_definition="Atmospheric pressure exerted by the weight of air directly at the Earth's topography elevation.",
        units="hPa",
        dataset_short_name="M2TMNXSLV",
        version="5.12.4",
        source_variable="PS",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="pa_to_hpa",
        native_resolution="0.5 x 0.625 degree (361 x 576)",
        scale_factor=0.01,
    ),
    "merra2_tqv": VariableConfig(
        id="merra2_tqv",
        name="Total Column Water Vapor (MERRA-2)",
        student_definition="Total integrated mass of gaseous water vapor in an atmospheric column extending from surface to space.",
        units="kg/m^2",
        dataset_short_name="M2TMNXSLV",
        version="5.12.4",
        source_variable="TQV",
        source_group=None,
        file_format="nc4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="monthly_mean",
        native_resolution="0.5 x 0.625 degree (361 x 576)",
    ),
    "modis_ndvi": VariableConfig(
        id="modis_ndvi",
        name="Vegetation Greenness (NDVI)",
        student_definition="A satellite vegetation index indicating photosynthetic activity and canopy greenness ranging from -0.2 to 1.0.",
        units="1",
        dataset_short_name="MOD13C2",
        version="061",
        source_variable="_0_05_Deg_Monthly_NDVI",
        source_group=None,
        file_format="HDF4",
        time_range=("2000-06-01", "2025-09-01"),
        aggregation="scale_factor",
        native_resolution="0.05 degree (3600 x 7200)",
        scale_factor=0.0001,
    ),
}


def dump_yaml_config(output_path: Path = Path("src/variables.yaml")) -> None:
    """Export the configurations to human-readable YAML."""
    raw_dict = {k: asdict(v) for k, v in VARIABLES.items()}
    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(raw_dict, f, sort_keys=False, indent=2)
    print(f"[+] Wrote variable configurations to {output_path}")


if __name__ == "__main__":
    dump_yaml_config()
