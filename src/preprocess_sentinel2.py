"""Extract Sentinel-2 L2A ZIP files and create scaled, multiband GeoTIFFs."""

import argparse
import importlib.util
import math
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

_rasterio_spec = importlib.util.find_spec("rasterio")
if _rasterio_spec is not None and _rasterio_spec.origin is not None:
    _rasterio_data_dir = Path(_rasterio_spec.origin).parent
    _proj_data_dir = _rasterio_data_dir / "proj_data"
    if (_proj_data_dir / "proj.db").is_file():
        os.environ["PROJ_DATA"] = str(_proj_data_dir)
        os.environ.pop("PROJ_LIB", None)
    _gdal_data_dir = _rasterio_data_dir / "gdal_data"
    if _gdal_data_dir.is_dir():
        os.environ["GDAL_DATA"] = str(_gdal_data_dir)

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject

import config


def _configured_bands() -> tuple[str, ...]:
    bands = config.BANDS
    if config.INCLUDE_20M_BANDS:
        bands += config.BANDS_20M
    return tuple(dict.fromkeys(bands))


def _extract_archive(archive_path: Path, extraction_path: Path) -> Path:
    bands_to_process = _configured_bands()
    requested_bands = {
        band: re.compile(rf"_{re.escape(band)}_(\d+)m\.jp2$", re.IGNORECASE)
        for band in bands_to_process
    }
    granules: dict[str, dict[str, list[tuple[int, zipfile.ZipInfo]]]] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            member_path = PurePosixPath(member.filename.replace("\\", "/"))
            if member_path.is_absolute() or ".." in member_path.parts:
                raise ValueError(f"Unsafe path in ZIP archive: {member.filename}")
            if member_path.parts and ":" in member_path.parts[0]:
                raise ValueError(f"Unsafe path in ZIP archive: {member.filename}")
            parts = member_path.parts
            if member.is_dir() or member_path.suffix.lower() != ".jp2":
                continue
            try:
                granule_index = parts.index("GRANULE")
            except ValueError:
                continue
            if (
                granule_index == 0
                or not parts[granule_index - 1].upper().endswith(".SAFE")
                or len(parts) <= granule_index + 4
                or parts[granule_index + 2] != "IMG_DATA"
            ):
                continue

            match_band = next(
                (
                    (band, pattern.search(member_path.name))
                    for band, pattern in requested_bands.items()
                    if pattern.search(member_path.name)
                ),
                None,
            )
            if match_band is None:
                continue
            band, match = match_band
            granule = parts[granule_index + 1]
            granules.setdefault(granule, {}).setdefault(band, []).append(
                (int(match.group(1)), member)
            )

        if not granules:
            raise FileNotFoundError(
                f"No configured Sentinel-2 bands found in {archive_path}"
            )
        for granule, bands in granules.items():
            missing_bands = set(requested_bands) - bands.keys()
            if missing_bands:
                raise FileNotFoundError(
                    f"Missing configured bands for granule {granule}: "
                    f"{', '.join(sorted(missing_bands))}"
                )

            img_data_dir = extraction_path / granule / "IMG_DATA"
            for band, candidates in bands.items():
                preferred_resolution = (
                    20
                    if config.INCLUDE_20M_BANDS and band in config.BANDS_20M
                    else config.TARGET_RESOLUTION_M
                )
                resolution, member = min(
                    candidates,
                    key=lambda candidate: (
                        abs(candidate[0] - preferred_resolution),
                        -candidate[0],
                    ),
                )
                destination = img_data_dir / f"R{resolution}m" / PurePosixPath(
                    member.filename.replace("\\", "/")
                ).name
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)

    if not _find_img_data_dirs(extraction_path):
        raise FileNotFoundError(
            f"No SAFE/GRANULE/*/IMG_DATA directory found in {archive_path}"
        )
    return extraction_path


def _find_img_data_dirs(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("IMG_DATA")
        if path.is_dir()
    )


def _find_band_file(img_data_dir: Path, band: str) -> Path:
    pattern = re.compile(rf"_{re.escape(band)}_(\d+)m\.jp2$", re.IGNORECASE)
    candidates: list[tuple[int, Path]] = []
    for path in img_data_dir.rglob("*.jp2"):
        match = pattern.search(path.name)
        if match:
            candidates.append((int(match.group(1)), path))

    if not candidates:
        raise FileNotFoundError(f"Band {band} not found in {img_data_dir}")

    candidates.sort(
        key=lambda candidate: (
            abs(candidate[0] - config.TARGET_RESOLUTION_M),
            -candidate[0],
        )
    )
    return candidates[0][1]


def _create_multiband_raster(img_data_dir: Path, output_path: Path) -> Path:
    bands_to_process = _configured_bands()
    if not bands_to_process:
        raise ValueError("Set at least one band in preprocessing/config.py.")
    if config.TARGET_RESOLUTION_M <= 0 or config.SCALE_FACTOR <= 0:
        raise ValueError("Target resolution and scale factor must be greater than zero.")

    band_files = [
        (band, _find_band_file(img_data_dir, band)) for band in bands_to_process
    ]
    with rasterio.open(band_files[0][1]) as reference:
        target_crs = reference.crs
        if target_crs is None:
            raise ValueError(f"Input raster has no CRS: {band_files[0][1]}")
        if not target_crs.is_projected:
            raise ValueError(
                f"Target resolution is in metres, but the input CRS is not projected: "
                f"{target_crs}"
            )

        bounds = reference.bounds
        resolution = config.TARGET_RESOLUTION_M
        width = math.ceil((bounds.right - bounds.left) / resolution - 1e-9)
        height = math.ceil((bounds.top - bounds.bottom) / resolution - 1e-9)
        if width <= 0 or height <= 0:
            raise ValueError(f"Invalid output dimensions for {band_files[0][1]}")
        transform = from_origin(bounds.left, bounds.top, resolution, resolution)
        profile = {
            "driver": "GTiff",
            "width": width,
            "height": height,
            "count": len(band_files),
            "dtype": "float32",
            "crs": target_crs,
            "transform": transform,
            "tiled": True,
            "blockxsize": 512,
            "blockysize": 512,
            "compress": "deflate",
            "predictor": 3,
            "BIGTIFF": "IF_SAFER",
        }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    try:
        with rasterio.open(temporary_path, "w", **profile) as destination:
            for index, (band, band_path) in enumerate(band_files, start=1):
                with rasterio.open(band_path) as source:
                    if source.crs is None:
                        raise ValueError(f"Input raster has no CRS: {band_path}")
                    data = np.zeros((height, width), dtype=np.float32)
                    reproject(
                        source=rasterio.band(source, 1),
                        destination=data,
                        src_transform=source.transform,
                        src_crs=source.crs,
                        src_nodata=source.nodata,
                        dst_transform=transform,
                        dst_crs=target_crs,
                        dst_nodata=0,
                        resampling=Resampling.bilinear,
                        init_dest_nodata=True,
                    )
                    data /= config.SCALE_FACTOR
                    destination.write(data, index)
                    destination.set_band_description(index, band)
                    del data
            destination.update_tags(
                scale_factor=config.SCALE_FACTOR,
                source="Sentinel-2 L2A",
            )
        temporary_path.replace(output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()

    return output_path


def process_archive(archive_path: Path) -> list[Path]:
    archive_path = archive_path.expanduser().resolve()
    if not archive_path.is_file():
        raise FileNotFoundError(f"ZIP archive not found: {archive_path}")
    if archive_path.suffix.lower() != ".zip":
        raise ValueError(f"Expected a ZIP archive: {archive_path}")

    config.EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f"{archive_path.stem}_",
        dir=config.EXTRACT_DIR,
    ) as temporary_dir:
        extraction_path = _extract_archive(archive_path, Path(temporary_dir))
        img_data_dirs = _find_img_data_dirs(extraction_path)
        outputs = []
        for img_data_dir in img_data_dirs:
            granule_name = img_data_dir.parent.name
            output_name = f"{archive_path.stem}_{granule_name}.tif"
            outputs.append(
                _create_multiband_raster(img_data_dir, config.OUTPUT_DIR / output_name)
            )
        return outputs


def process_archives(archive_paths: list[Path] | None = None) -> list[Path]:
    archives = (
        archive_paths
        if archive_paths is not None
        else sorted(config.INPUT_ZIP_DIR.glob("*.zip"))
    )
    if not archives:
        raise FileNotFoundError(f"No ZIP archives found in {config.INPUT_ZIP_DIR}")

    outputs = []
    for archive_path in archives:
        outputs.extend(process_archive(archive_path))
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extract Sentinel-2 L2A ZIP files and stack configured bands."
    )
    parser.add_argument(
        "archive",
        nargs="?",
        type=Path,
        help="ZIP archive to process; by default all ZIP files in the configured input folder.",
    )
    args = parser.parse_args()

    archives = [args.archive] if args.archive is not None else None
    for output_path in process_archives(archives):
        print(f"Created: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
