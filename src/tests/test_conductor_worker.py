import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import config
import preprocess_sentinel2
from conductor_worker import _settings_from_input


class SettingsFromTaskInputTests(unittest.TestCase):
    def test_missing_values_use_config_defaults(self):
        self.assertEqual(_settings_from_input({}), config.DEFAULT_SETTINGS)

    def test_all_settings_can_be_overridden(self):
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            settings = _settings_from_input(
                {
                    "workspace_dir": str(root / "project"),
                    "input_zip_dir": str(root / "input"),
                    "extract_dir": str(root / "temp"),
                    "output_dir": str(root / "output"),
                    "bands": ["B04", "B08"],
                    "include_20m_bands": False,
                    "bands_20m": ["B11"],
                    "target_resolution_m": 20,
                    "scale_factor": 1000,
                    "delete_extracted_bands_after_merge": False,
                }
            )

        self.assertEqual(settings.workspace_dir, root / "project")
        self.assertEqual(settings.input_zip_dir, root / "input")
        self.assertEqual(settings.extract_dir, root / "temp")
        self.assertEqual(settings.output_dir, root / "output")
        self.assertEqual(settings.bands, ("B04", "B08"))
        self.assertFalse(settings.include_20m_bands)
        self.assertEqual(settings.bands_20m, ("B11",))
        self.assertEqual(settings.target_resolution_m, 20)
        self.assertEqual(settings.scale_factor, 1000)
        self.assertFalse(settings.delete_extracted_bands_after_merge)

    def test_workspace_override_updates_default_input_directory(self):
        with TemporaryDirectory() as temporary_dir:
            workspace_dir = Path(temporary_dir) / "project"
            settings = _settings_from_input(
                {"workspace_dir": str(workspace_dir)}
            )

        self.assertEqual(
            settings.input_zip_dir,
            workspace_dir / "eodag" / "downloads",
        )

    def test_invalid_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "target_resolution_m"):
            _settings_from_input({"target_resolution_m": 0})

        with self.assertRaisesRegex(ValueError, "include_20m_bands"):
            _settings_from_input({"include_20m_bands": "false"})

        with self.assertRaisesRegex(
            ValueError,
            "delete_extracted_bands_after_merge",
        ):
            _settings_from_input({"delete_extracted_bands_after_merge": "false"})

        with self.assertRaisesRegex(ValueError, "Unknown preprocessing task input"):
            _settings_from_input({"target_resoluton_m": 20})


class ExtractedBandsCleanupTests(unittest.TestCase):
    def test_extracted_bands_are_deleted_after_merge_by_default(self):
        self._process_archive_and_check_retention(delete_extracted_bands=True)

    def test_extracted_bands_can_be_kept_after_merge(self):
        self._process_archive_and_check_retention(delete_extracted_bands=False)

    def _process_archive_and_check_retention(self, delete_extracted_bands: bool):
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            archive_path = root / "sentinel.zip"
            archive_path.touch()
            extraction_dir = root / "extracted"
            settings = config.PreprocessingSettings(
                extract_dir=extraction_dir,
                output_dir=root / "output",
                delete_extracted_bands_after_merge=delete_extracted_bands,
            )

            def extract_archive(archive, extraction_path, settings):
                band_dir = extraction_path / "G1" / "IMG_DATA"
                band_dir.mkdir(parents=True)
                (band_dir / "B04_10m.jp2").touch()
                return extraction_path

            with (
                patch.object(
                    preprocess_sentinel2,
                    "_extract_archive",
                    side_effect=extract_archive,
                ),
                patch.object(
                    preprocess_sentinel2,
                    "_find_img_data_dirs",
                    side_effect=lambda path: [path / "G1" / "IMG_DATA"],
                ),
                patch.object(
                    preprocess_sentinel2,
                    "_create_multiband_raster",
                    side_effect=lambda img_dir, output_path, settings: output_path,
                ),
            ):
                outputs = preprocess_sentinel2.process_archive(archive_path, settings)

            self.assertEqual(len(outputs), 1)
            retained_dirs = list(extraction_dir.iterdir())
            if delete_extracted_bands:
                self.assertEqual(retained_dirs, [])
            else:
                self.assertEqual(len(retained_dirs), 1)
                self.assertTrue(
                    (retained_dirs[0] / "G1" / "IMG_DATA" / "B04_10m.jp2").is_file()
                )


if __name__ == "__main__":
    unittest.main()
