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
