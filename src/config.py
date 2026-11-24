from dataclasses import dataclass
from pathlib import Path


WORKSPACE_DIR = Path(__file__).resolve().parent.parent
INPUT_ZIP_DIR = WORKSPACE_DIR / "eodag" / "downloads"
EXTRACT_DIR = Path(__file__).resolve().parent / "extracted"
OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# Change these values to select the bands and output pixel size for your analysis.
BANDS = ("B02", "B03", "B04", "B08")
# Optionally append all Sentinel-2 bands provided at 20 m and resample them
# to TARGET_RESOLUTION_M in the output dataset.
INCLUDE_20M_BANDS = True
BANDS_20M = ("B05", "B06", "B07", "B8A", "B11", "B12")
TARGET_RESOLUTION_M = 10
SCALE_FACTOR = 10_000
DELETE_EXTRACTED_BANDS_AFTER_MERGE = True


@dataclass(frozen=True)
class PreprocessingSettings:
    workspace_dir: Path = WORKSPACE_DIR
    input_zip_dir: Path = INPUT_ZIP_DIR
    extract_dir: Path = EXTRACT_DIR
    output_dir: Path = OUTPUT_DIR
    bands: tuple[str, ...] = BANDS
    include_20m_bands: bool = INCLUDE_20M_BANDS
    bands_20m: tuple[str, ...] = BANDS_20M
    target_resolution_m: float = TARGET_RESOLUTION_M
    scale_factor: float = SCALE_FACTOR
    delete_extracted_bands_after_merge: bool = DELETE_EXTRACTED_BANDS_AFTER_MERGE


DEFAULT_SETTINGS = PreprocessingSettings()
