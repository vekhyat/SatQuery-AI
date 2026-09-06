"""Synthetic geospatial regression tests: correctness, failure paths, and artifacts."""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
import rasterio
from rasterio.transform import from_origin, from_bounds
from rasterio.warp import transform_bounds

from satquery.tools.tool3 import BandSource, Config, DatasetError, check_dataset, discover, load_manifest, run_pipeline
from satquery.tools.tool3.evaluation import evaluate_arrays, evaluate_files
from satquery.tools.tool3.cli import main
from satquery.tools.tool3.inputs import identify, inspect_source, read_aligned, resolve_sar_units
from satquery.tools.tool3.pipeline import clean_mask, normalized_difference


class Tool3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.transform = from_origin(500000, 3100000, 10, 10)
        self.config = Config(sar_units="linear", morphology_size=1, speckle_size=1, min_component_pixels=1)
        self.data = {"green": np.full((32, 32), .12, np.float32), "nir": np.full((32, 32), .3, np.float32),
                     "swir": np.full((32, 32), .2, np.float32), "red": np.full((32, 32), .1, np.float32),
                     "vv": np.full((32, 32), .1, np.float32), "vh": np.full((32, 32), .025, np.float32)}
        for role, value in (("green", .3), ("nir", .05), ("swir", .02), ("red", .02)):
            self.data[role][3:11, 3:11] = value
        for role, value in (("green", .1), ("nir", .2), ("swir", .4), ("red", .2)):
            self.data[role][18:27, 3:11] = value
        for role, value, bright in (("vv", .001, .8), ("vh", .0003, .2)):
            self.data[role][3:11, 3:11] = value
            self.data[role][3:11, 18:26] = value
            self.data[role][18:27, 18:26] = bright
        self.sources = {role: self.write(role, value) for role, value in self.data.items()}

    def write(self, name, data, transform=None, crs="EPSG:32643", nodata=None, mask=None, descriptions=None, tags=None):
        path = self.root / f"{name}.tif"
        array = data if data.ndim == 3 else data[None, :, :]
        with rasterio.open(path, "w", driver="GTiff", width=array.shape[2], height=array.shape[1],
                           count=array.shape[0], dtype=array.dtype, crs=crs,
                           transform=transform if transform is not None else self.transform, nodata=nodata) as dst:
            dst.write(array)
            if mask is not None:
                dst.write_mask(mask.astype(np.uint8) * 255)
            if descriptions:
                dst.descriptions = descriptions
            if tags:
                dst.update_tags(**tags)
        return BandSource(path)

    def run_pair(self, sources=None, config=None):
        return run_pipeline(sources or self.sources, self.root / "output", config or self.config)

    def read(self, result, name="fused"):
        with rasterio.open(Path(result["receipt"]["output_dir"]) / f"{name}.tif") as src:
            return src.read(1)

    def test_end_to_end_known_regions_and_artifact_contract(self):
        result = self.run_pair()
        fused = self.read(result)
        self.assertEqual(fused[5, 5], 1)
        self.assertEqual(fused[5, 20], 1)
        self.assertEqual(fused[20, 5], 2)
        self.assertEqual(fused[20, 20], 2)
        self.assertEqual(fused[15, 15], 0)
        self.assertEqual(result["facts"]["sar_added_water_pixels"], 64)
        self.assertEqual(result["facts"]["sar_added_builtup_pixels"], 72)
        self.assertTrue(result["facts"]["fused_differs_from_optical"])
        self.assertEqual(result["facts"]["pixel_area_m2"], 100)
        folder = Path(result["receipt"]["output_dir"])
        for name in result["receipt"]["artifacts"]:
            self.assertTrue((folder / name).is_file(), name)
        self.assertEqual(json.loads((folder / "result.json").read_text()), result)
        self.assertNotIn("__FACTS__", (folder / "report.html").read_text(encoding="utf-8"))
        with rasterio.open(folder / "fused.tif") as src:
            self.assertEqual(src.transform, self.transform)
            self.assertEqual(src.crs.to_epsg(), 32643)
            self.assertEqual(src.nodata, 255)
            self.assertTrue(src.read_masks(1)[15, 15])  # Other class is valid, not nodata.
        with Image.open(folder / "fused.png") as png:
            self.assertEqual(png.mode, "RGBA")
            self.assertEqual(png.getpixel((5, 5)), (39, 164, 242, 255))

    def test_db_and_linear_inputs_produce_same_classes(self):
        linear = self.run_pair()
        for role in ("vv", "vh"):
            self.sources[role] = self.write(role, 10 * np.log10(self.data[role]))
        decibels = self.run_pair(config=replace(self.config, sar_units="db"))
        np.testing.assert_array_equal(self.read(linear), self.read(decibels))

    def test_zero_db_is_valid_and_not_confused_with_linear_zero(self):
        for role in ("vv", "vh"):
            self.sources[role] = self.write(role, np.zeros((32, 32), np.float32))
        result = self.run_pair(config=replace(self.config, sar_units="db"))
        self.assertEqual(result["facts"]["layers"]["sar_only"]["valid_pixels"], 1024)

    def test_different_resolution_preserves_geographic_location(self):
        for role in ("vv", "vh"):
            enlarged = self.data[role].repeat(2, axis=0).repeat(2, axis=1)
            self.sources[role] = self.write(role, enlarged, from_origin(500000, 3100000, 5, 5))
        result = self.run_pair()
        self.assertEqual(self.read(result, "sar_only")[5, 20], 1)
        self.assertIn("reprojected", result["receipt"]["inputs"]["vv"]["alignment"])

    def test_shifted_origin_is_warped_not_resized(self):
        for role in ("vv", "vh"):
            self.sources[role] = self.write(role, self.data[role], from_origin(500020, 3100000, 10, 10))
        result = self.run_pair()
        sar = self.read(result, "sar_only")
        self.assertTrue(np.all(sar[:, :2] == 255))
        self.assertEqual(sar[5, 27], 1)
        self.assertEqual(sar[5, 18], 0)
        self.assertAlmostEqual(result["facts"]["overlap_fraction_of_optical"], 30 / 32)

    def test_different_crs_is_reprojected(self):
        bounds = transform_bounds("EPSG:32643", "EPSG:4326", 500000, 3099680, 500320, 3100000)
        for role in ("vv", "vh"):
            self.sources[role] = self.write(role, self.data[role], from_bounds(*bounds, 32, 32), crs="EPSG:4326")
        result = self.run_pair()
        self.assertGreater(result["facts"]["overlap_fraction_of_optical"], .9)
        self.assertEqual(self.read(result, "sar_only")[6, 22], 1)

    def test_no_geographic_overlap_rejects(self):
        self.sources["vv"] = self.write("vv", self.data["vv"], from_origin(900000, 3100000, 10, 10))
        with self.assertRaisesRegex(DatasetError, "does not overlap"):
            self.run_pair()
        self.assertFalse((self.root / "output").exists())

    def test_partial_overlap_below_minimum_rejects(self):
        for role in ("vv", "vh"):
            self.sources[role] = self.write(role, self.data[role], from_origin(500250, 3100000, 10, 10))
        with self.assertRaisesRegex(DatasetError, "overlaps only"):
            self.run_pair()

    def test_nodata_and_nan_do_not_become_detections(self):
        for role, array in self.data.items():
            array[0:3, 0:3] = -9999
            array[12:14, 12:14] = np.nan
            self.sources[role] = self.write(role, array, nodata=-9999)
        result = self.run_pair()
        self.assertTrue(np.all(self.read(result)[:3, :3] == 255))
        self.assertTrue(np.all(self.read(result)[12:14, 12:14] == 255))

    def test_internal_validity_masks_are_respected(self):
        mask = np.ones((32, 32), bool)
        mask[:3, :3] = False
        for role, array in self.data.items():
            self.sources[role] = self.write(role, array, mask=mask)
        self.assertTrue(np.all(self.read(self.run_pair())[:3, :3] == 255))

    def test_all_invalid_sar_rejects_without_percentile_error(self):
        self.sources["vv"] = self.write("vv", np.zeros((32, 32), np.float32))
        with self.assertRaisesRegex(DatasetError, "no valid positive power"):
            self.run_pair()

    def test_all_invalid_optical_rejects(self):
        for role in ("green", "nir", "swir"):
            self.sources[role] = self.write(role, np.zeros((32, 32), np.float32))
        with self.assertRaisesRegex(DatasetError, "no jointly valid"):
            self.run_pair()

    def test_cloud_mask_excludes_optical_and_sar_supplies_coverage(self):
        scl = np.full((32, 32), 4, np.uint8)
        scl[3:11, 18:26] = 9
        self.sources["scl"] = self.write("scl", scl)
        result = self.run_pair()
        self.assertEqual(self.read(result, "optical_only")[5, 20], 255)
        self.assertEqual(self.read(result)[5, 20], 1)
        self.assertEqual(result["facts"]["sar_filled_quality_masked_pixels"], 64)

    def test_fully_cloudy_scene_falls_back_to_sar(self):
        self.sources["scl"] = self.write("scl", np.full((32, 32), 9, np.uint8))
        result = self.run_pair()
        self.assertEqual(result["facts"]["layers"]["optical_only"]["valid_pixels"], 0)
        self.assertIsNone(result["facts"]["sensor_agreement_fraction"])
        np.testing.assert_array_equal(self.read(result), self.read(result, "sar_only"))

    def test_invalid_scl_codes_reject(self):
        self.sources["scl"] = self.write("scl", np.full((32, 32), .5, np.float32))
        with self.assertRaisesRegex(DatasetError, "SCL must"):
            self.run_pair()

    def test_single_vv_is_supported_with_warning(self):
        del self.sources["vh"]
        result = self.run_pair()
        self.assertTrue(any("VV only" in warning for warning in result["warnings"]))

    def test_missing_required_band_rejects(self):
        del self.sources["swir"]
        with self.assertRaisesRegex(DatasetError, "Missing required bands: swir"):
            self.run_pair()

    def test_same_file_band_cannot_be_assigned_multiple_roles(self):
        self.sources["nir"] = self.sources["green"]
        with self.assertRaisesRegex(DatasetError, "same file and band"):
            self.run_pair()

    def test_missing_crs_rejects(self):
        self.sources["green"] = self.write("green", self.data["green"], crs=None)
        with self.assertRaisesRegex(DatasetError, "no CRS"):
            self.run_pair()

    def test_oversized_input_rejects_before_allocation(self):
        with self.assertRaisesRegex(DatasetError, "exceeds max_pixels"):
            self.run_pair(config=replace(self.config, max_pixels=100))

    def test_geographic_grid_does_not_report_square_degrees_as_hectares(self):
        for role, value in self.data.items():
            self.sources[role] = self.write(role, value, from_origin(75, 28, .0001, .0001), crs="EPSG:4326")
        result = self.run_pair()
        self.assertIsNone(result["facts"]["pixel_area_m2"])
        self.assertIsNone(result["facts"]["layers"]["fused"]["water"]["area_ha"])
        with self.assertRaisesRegex(DatasetError, "requires a projected"):
            self.run_pair(config=replace(self.config, min_component_m2=100))

    def test_identical_maps_are_reported_honestly(self):
        for role, value in (("green", .1), ("nir", .3), ("swir", .2), ("red", .1), ("vv", .1), ("vh", .025)):
            self.sources[role] = self.write(role, np.full((32, 32), value, np.float32))
        result = self.run_pair()
        self.assertFalse(result["facts"]["fused_differs_from_optical"])
        self.assertIn("no additional", result["facts"]["sar_contribution"])

    def test_water_priority_and_contribution_counts_exclude_suppressed_builtup(self):
        self.data["vv"][18:27, 3:11] = .001
        self.data["vh"][18:27, 3:11] = .0003
        for role in ("vv", "vh"):
            self.sources[role] = self.write(role, self.data[role])
        result = self.run_pair()
        self.assertEqual(self.read(result)[20, 5], 1)
        self.assertEqual(result["facts"]["optical_builtup_replaced_by_water_pixels"], 72)
        self.assertEqual(result["facts"]["sar_added_builtup_pixels"], 72)

    def test_optical_scale_offset_matches_reflectance_input(self):
        reference = self.run_pair()
        for role in ("green", "nir", "swir", "red"):
            raw = np.round((self.data[role] + .1) * 10000).astype(np.uint16)
            spec = self.write(role, raw)
            self.sources[role] = replace(spec, scale=.0001, offset=-.1)
        calibrated = self.run_pair()
        np.testing.assert_array_equal(self.read(reference), self.read(calibrated))

    def test_multiband_manifest_relative_paths(self):
        optical_roles = ["green", "nir", "swir", "red"]
        self.write("optical_stack", np.stack([self.data[r] for r in optical_roles]))
        self.write("sar_stack", np.stack([self.data[r] for r in ["vv", "vh"]]))
        manifest = {"bands": {r: {"path": "optical_stack.tif", "band": i + 1} for i, r in enumerate(optical_roles)},
                    "parameters": {"sar_units": "linear"}}
        manifest["bands"].update({r: {"path": "sar_stack.tif", "band": i + 1} for i, r in enumerate(["vv", "vh"])})
        path = self.root / "dataset.json"
        path.write_text(json.dumps(manifest))
        sources, parameters = load_manifest(path)
        self.assertEqual(parameters["sar_units"], "linear")
        result = self.run_pair(sources=sources)
        self.assertEqual(self.read(result)[5, 20], 1)

    def test_discovery_rejects_duplicate_candidates(self):
        self.write("green_copy", self.data["green"])
        with self.assertRaisesRegex(DatasetError, "Multiple candidates"):
            discover(self.root, self.root)

    def test_discovery_uses_band_descriptions_for_stacks(self):
        folder = self.root / "stacks"
        folder.mkdir()
        spec = self.write("stack", np.stack(list(self.data.values())), descriptions=tuple(self.data.keys()))
        spec.path.rename(folder / "stack.tif")
        sources = discover(folder, folder)
        self.assertEqual(sources["nir"].band, 2)
        self.assertEqual(sources["vh"].band, 6)

    def test_filename_detection_does_not_guess_rgb_or_ambiguous_polarization(self):
        self.assertEqual(identify("Sentinel-1_IW_VV_VH_VV_(Raw)"), "vv")
        self.assertEqual(identify("S2_B03_10m"), "green")
        self.assertIsNone(identify("VV_VH"))
        self.assertIsNone(identify("B8A"))
        self.assertIsNone(identify("RGB"))

    def test_unknown_sar_units_require_explicit_configuration(self):
        with self.assertRaisesRegex(DatasetError, "SAR units are unknown"):
            self.run_pair(config=replace(self.config, sar_units="auto"))

    def test_metadata_sar_units_are_used(self):
        for role in ("vv", "vh"):
            self.sources[role] = self.write(role, 10 * np.log10(self.data[role]), tags={"units": "dB"})
        result = self.run_pair(config=replace(self.config, sar_units="auto"))
        self.assertEqual(result["receipt"]["inputs"]["vv"]["resolved_units"], "db")

    def test_dates_within_one_modality_must_match(self):
        self.sources["green"] = self.write("green", self.data["green"], tags={"ACQUISITION_DATE": "2026-04-01"})
        self.sources["nir"] = self.write("nir", self.data["nir"], tags={"ACQUISITION_DATE": "2026-04-02"})
        with self.assertRaisesRegex(DatasetError, "different acquisition dates"):
            self.run_pair()

    def test_excessive_sensor_date_gap_rejects(self):
        for role, value in self.data.items():
            day = "2026-04-01" if role not in {"vv", "vh"} else "2026-06-01"
            self.sources[role] = self.write(role, value, tags={"ACQUISITION_DATE": day})
        with self.assertRaisesRegex(DatasetError, "61 days apart"):
            self.run_pair()

    def test_repeated_runs_preserve_previous_results(self):
        first = self.run_pair()
        first_file = Path(first["receipt"]["output_dir"]) / "result.json"
        original = first_file.read_bytes()
        second = self.run_pair()
        self.assertNotEqual(first["receipt"]["run_id"], second["receipt"]["run_id"])
        self.assertEqual(first_file.read_bytes(), original)
        latest = json.loads((self.root / "output" / "latest.json").read_text())
        self.assertEqual(latest["run_id"], second["receipt"]["run_id"])
        self.assertFalse(list((self.root / "output").glob(".pending_*")))

    def test_importing_old_entrypoints_has_no_side_effects(self):
        project = Path(__file__).resolve().parents[2]
        script = f"import sys; sys.path.insert(0, {str(project)!r}); import satquery.tools.optical_sar, satquery.tools.tool3.cli, satquery.tools.tool3.evaluate_cli, satquery.tools.tool3.demo"
        process = subprocess.run([sys.executable, "-c", script], cwd=self.root, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, "")
        self.assertFalse((self.root / "output").exists())

    def test_cli_returns_json_rejection_for_missing_directory(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(["--optical-dir", str(self.root / "missing"), "--json"])
        self.assertEqual(code, 2)
        result = json.loads(stream.getvalue())
        self.assertTrue(result["receipt"]["rejected"])
        self.assertIsNone(result["overlay"]["file"])

    def test_invalid_parameters_are_actionable(self):
        for values in ({"min_overlap": 0}, {"morphology_size": 2}, {"max_pixels": -1},
                       {"sar_units": []}, {"ndwi_threshold": float("nan")}, {"min_component_pixels": 1.5}):
            with self.subTest(values=values), self.assertRaises(DatasetError):
                Config(**values)

    def test_morphology_cannot_fill_invalid_holes(self):
        valid = np.ones((20, 20), bool)
        valid[8:11, 8:11] = False
        cleaned = clean_mask(np.ones(valid.shape, bool), valid, 5, 1)
        self.assertFalse(cleaned[8:11, 8:11].any())

    def test_indices_do_not_overflow_unsigned_inputs(self):
        a = np.array([.1, 0, np.nan], np.float32)
        b = np.array([.3, 0, .2], np.float32)
        output = normalized_difference(a, b)
        self.assertAlmostEqual(float(output[0]), -.5, places=6)
        self.assertTrue(np.isnan(output[1:]).all())
        unsigned = normalized_difference(np.array([100, 60000], np.uint16), np.array([300, 60000], np.uint16))
        np.testing.assert_allclose(unsigned, [-.5, 0], atol=1e-6)

    def test_nodata_override_replaces_header_but_preserves_explicit_masks(self):
        for role in ("vv", "vh"):
            spec = self.write(role, np.zeros((32, 32), np.float32), nodata=0)
            self.sources[role] = replace(spec, nodata=-9999)
        result = self.run_pair(config=replace(self.config, sar_units="db"))
        self.assertEqual(result["facts"]["layers"]["sar_only"]["valid_pixels"], 1024)
        mask = np.ones((32, 32), bool)
        mask[:4] = False
        spec = self.write("vv", np.zeros((32, 32), np.float32), nodata=0, mask=mask)
        self.sources["vv"] = replace(spec, nodata=-9999)
        result = self.run_pair(config=replace(self.config, sar_units="db"))
        self.assertTrue(np.all(self.read(result, "sar_only")[:4] == 255))

    def test_cloudy_native_pixels_do_not_contaminate_clear_resampled_pixels(self):
        green = np.full((32, 32), .24, np.float32)
        nir = np.full((32, 32), .3, np.float32)
        nir[:, :8] = 0  # Cloud/shadow samples would create false water after interpolation.
        self.sources["green"] = self.write("green", green)
        self.sources["nir"] = self.write("nir", nir, from_origin(500002.5, 3100000, 10, 10))
        scl = np.full((32, 32), 4, np.uint8)
        scl[:, :8] = 9
        self.sources["scl"] = self.write("scl", scl)
        result = self.run_pair()
        self.assertEqual(self.read(result, "optical_only")[15, 8], 0)
        self.assertAlmostEqual(float(self.read(result, "ndwi")[15, 8]), -.111111, places=5)
        self.assertTrue(result["receipt"]["inputs"]["nir"]["quality_masked_before_resampling"])

    def test_check_only_does_not_read_pixels_or_write_output(self):
        with patch("satquery.tools.tool3.pipeline.read_aligned", side_effect=AssertionError("read pixels")):
            result = check_dataset(self.sources, self.config)
        self.assertEqual(result["status"], "metadata_valid")
        self.assertIn("pixel values and nodata coverage", result["not_checked"])
        self.assertFalse((self.root / "output").exists())

    def test_duplicate_json_band_key_rejects(self):
        manifest = self.root / "duplicate.json"
        manifest.write_text('{"bands":{"green":"a.tif","green":"b.tif"}}')
        with self.assertRaisesRegex(DatasetError, "Duplicate JSON key: green"):
            load_manifest(manifest)

    def test_empty_paths_boolean_and_extreme_numeric_parameters_reject(self):
        for kwargs in ({"path": ""}, {"path": None}, {"path": "a.tif", "scale": True},
                       {"path": "a.tif", "offset": 10 ** 1000}):
            with self.subTest(kwargs=kwargs), self.assertRaises(DatasetError):
                BandSource(**kwargs)
        for kwargs in ({"ndwi_threshold": True}, {"min_overlap": False}, {"min_component_m2": 10 ** 1000}):
            with self.subTest(kwargs=kwargs), self.assertRaises(DatasetError):
                Config(**kwargs)

    def test_conflicting_sar_unit_metadata_requires_override(self):
        self.sources["vv"] = self.write("vv", self.data["vv"], tags={"UNITS": "dB", "UNITTYPE": "linear_power"})
        with self.assertRaisesRegex(DatasetError, "Conflicting SAR unit metadata"):
            check_dataset(self.sources, replace(self.config, sar_units="auto"))
        self.assertEqual(check_dataset(self.sources, self.config)["status"], "metadata_valid")

    def write_manifest(self, filename="dataset.json"):
        manifest = {"bands": {role: {"path": spec.path.name, "band": spec.band} for role, spec in self.sources.items()},
                    "parameters": {"sar_units": "linear", "speckle_size": 1, "morphology_size": 1, "min_component_pixels": 1}}
        path = self.root / filename
        path.write_text(json.dumps(manifest))
        return path

    def test_cli_check_only_manifest(self):
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(["--manifest", str(self.write_manifest()), "--check-only", "--json", "--output-dir", str(self.root / "output")])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stream.getvalue())["check_only"])
        self.assertFalse((self.root / "output").exists())

    def test_batch_continues_after_missing_manifest_and_saves_summary(self):
        self.write_manifest()
        batch = self.root / "batch.json"
        batch.write_text(json.dumps({"datasets": [{"name": "bad", "manifest": "missing.json"},
                                                   {"name": "good", "manifest": "dataset.json"}]}))
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(["--batch", str(batch), "--json", "--output-dir", str(self.root / "output")])
        result = json.loads(stream.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual((result["succeeded"], result["failed"]), (1, 1))
        self.assertEqual(result["datasets"][1]["status"], "completed")
        self.assertEqual(json.loads(Path(result["summary_file"]).read_text()), result)

    def test_batch_rejects_duplicate_names_and_path_traversal_before_running(self):
        batch = self.root / "batch.json"
        for names in (("scene", "SCENE"), ("../outside", "okay")):
            batch.write_text(json.dumps({"datasets": [{"name": name, "manifest": "a.json"} for name in names]}))
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = main(["--batch", str(batch), "--json", "--output-dir", str(self.root / "output")])
            self.assertEqual(code, 2)
            self.assertFalse((self.root / "output").exists())

    def test_batch_check_only_writes_nothing(self):
        self.write_manifest()
        batch = self.root / "batch.json"
        batch.write_text('{"datasets":[{"name":"a","manifest":"dataset.json"}]}')
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = main(["--batch", str(batch), "--check-only", "--json", "--output-dir", str(self.root / "output")])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stream.getvalue())["datasets"][0]["status"], "checked")
        self.assertFalse((self.root / "output").exists())

    def test_failed_write_does_not_publish_or_replace_last_success(self):
        result = self.run_pair()
        pointer = (self.root / "output/latest.json").read_bytes()
        with patch("satquery.tools.tool3.reporting.write_outputs", side_effect=OSError("Disk full")):
            with self.assertRaisesRegex(OSError, "Disk full"):
                self.run_pair()
        self.assertEqual((self.root / "output/latest.json").read_bytes(), pointer)
        self.assertEqual(len([p for p in (self.root / "output").iterdir() if p.is_dir()]), 1)

    def test_evaluation_metrics_match_hand_computed_confusion_matrix(self):
        reference = np.array([[0, 0, 1], [1, 2, 2]], np.uint8)
        prediction = np.array([[0, 1, 1], [2, 2, 0]], np.uint8)
        result = evaluate_arrays(prediction, reference)
        self.assertEqual(result["confusion_matrix"], [[1, 1, 0], [0, 1, 1], [1, 0, 1]])
        self.assertEqual(result["accuracy"], .5)
        self.assertAlmostEqual(result["mean_iou"], 1 / 3)
        self.assertEqual(result["macro_f1"], .5)

    def test_evaluation_reports_abstentions_and_absent_classes(self):
        reference = np.array([[0, 0, 255]], np.uint8)
        prediction = np.array([[0, 255, 1]], np.uint8)
        result = evaluate_arrays(prediction, reference)
        self.assertEqual(result["accuracy"], 1)
        self.assertEqual(result["prediction_coverage_of_reference"], .5)
        self.assertEqual(result["prediction_pixels_without_reference"], 1)
        self.assertIsNone(result["per_class"]["water"]["iou"])

    def test_evaluation_rejects_unknown_classes_and_empty_overlap(self):
        for reference in (np.full((2, 2), 10), np.full((2, 2), 255)):
            with self.assertRaises(DatasetError):
                evaluate_arrays(np.zeros((2, 2)), reference)

    def test_evaluation_reprojects_categorical_reference_and_handles_nodata_conflicts(self):
        labels = np.zeros((32, 32), np.uint8)
        labels[8:20, 8:20] = 1
        prediction = self.write("prediction", labels, nodata=255)
        reference = self.write("reference", labels.repeat(2, 0).repeat(2, 1), from_origin(500000, 3100000, 5, 5), nodata=0)
        with self.assertRaisesRegex(DatasetError, "nodata conflicts"):
            evaluate_files(prediction.path, reference.path)
        result = evaluate_files(prediction.path, reference.path, reference_nodata=255)
        self.assertEqual(result["accuracy"], 1)
        self.assertEqual(result["evaluated_pixels"], 1024)

    def test_oversized_component_threshold_produces_no_detections(self):
        self.assertFalse(clean_mask(np.ones((2, 2), bool), np.ones((2, 2), bool), 1, 10 ** 100).any())


if __name__ == "__main__":
    unittest.main()
