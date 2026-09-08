import importlib
import unittest

import numpy as np


try:
    analysis = importlib.import_module("experiments.tool2_mci.analysis")
except ImportError:
    analysis = None


class ChangeAnalysisModuleBoundaryTest(unittest.TestCase):
    def test_analysis_functions_are_available(self):
        self.assertIsNotNone(analysis, "The Tool 2 analysis module is not implemented")
        for name in (
            "compute_change_statistics",
            "extract_change_components",
            "physical_area_from_metadata",
        ):
            self.assertTrue(callable(getattr(analysis, name, None)), name)


@unittest.skipIf(analysis is None, "analysis module is not implemented")
class ChangeStatisticsTest(unittest.TestCase):
    def test_no_change_mask(self):
        stats = analysis.compute_change_statistics(np.zeros((2, 2), dtype=np.uint8))
        self.assertEqual(stats["total_pixels"], 4)
        self.assertEqual(stats["valid_pixels"], 4)
        self.assertEqual(stats["unchanged_pixels"], 4)
        self.assertEqual(stats["changed_pixels"], 0)
        self.assertEqual(stats["changed_fraction"], 0.0)
        self.assertEqual(stats["changed_percent"], 0.0)
        self.assertEqual(stats["classes"]["road_change"]["pixel_count"], 0)
        self.assertEqual(stats["classes"]["building_change"]["pixel_count"], 0)

    def test_only_road_change(self):
        stats = analysis.compute_change_statistics(np.ones((2, 3), dtype=np.uint8))
        road = stats["classes"]["road_change"]
        building = stats["classes"]["building_change"]
        self.assertEqual(stats["changed_pixels"], 6)
        self.assertEqual(stats["changed_fraction"], 1.0)
        self.assertEqual(road["pixel_count"], 6)
        self.assertEqual(road["percent_of_valid_pixels"], 100.0)
        self.assertEqual(road["percent_of_changed_pixels"], 100.0)
        self.assertEqual(building["percent_of_changed_pixels"], 0.0)

    def test_only_building_change(self):
        mask = np.full((3, 2), 2, dtype=np.uint8)
        stats = analysis.compute_change_statistics(mask)
        building = stats["classes"]["building_change"]
        self.assertEqual(stats["changed_pixels"], 6)
        self.assertEqual(building["pixel_count"], 6)
        self.assertEqual(building["percent_of_valid_pixels"], 100.0)
        self.assertEqual(building["percent_of_changed_pixels"], 100.0)

    def test_mixed_classes_and_valid_mask_obey_sum_invariants(self):
        mask = np.array([[0, 1], [2, 0]], dtype=np.uint8)
        valid = np.array([[True, True], [True, False]])
        stats = analysis.compute_change_statistics(mask, valid_mask=valid)
        classes = stats["classes"]
        counts = [item["pixel_count"] for item in classes.values()]
        self.assertEqual(stats["total_pixels"], 4)
        self.assertEqual(stats["valid_pixels"], 3)
        self.assertEqual(stats["unchanged_pixels"], 1)
        self.assertEqual(stats["changed_pixels"], 2)
        self.assertAlmostEqual(stats["changed_fraction"], 2 / 3)
        self.assertAlmostEqual(stats["changed_percent"], 200 / 3)
        self.assertEqual(sum(counts), stats["valid_pixels"])
        self.assertEqual(
            classes["road_change"]["pixel_count"]
            + classes["building_change"]["pixel_count"],
            stats["changed_pixels"],
        )

    def test_invalid_semantic_class_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "0, 1, and 2"):
            analysis.compute_change_statistics(np.array([[0, 3]], dtype=np.uint8))


@unittest.skipIf(analysis is None, "analysis module is not implemented")
class ChangeComponentsTest(unittest.TestCase):
    def test_empty_mask_has_no_components(self):
        result = analysis.extract_change_components(
            np.zeros((4, 4), dtype=np.uint8), min_pixels=2
        )
        for group in ("all_changed", "road_change", "building_change"):
            self.assertEqual(result[group]["raw_component_count"], 0)
            self.assertEqual(result[group]["filtered_component_count"], 0)
            self.assertIsNone(result[group]["largest_component_pixels"])
            self.assertEqual(result[group]["items"], [])

    def test_components_are_filtered_and_report_pixel_geometry(self):
        mask = np.zeros((6, 6), dtype=np.uint8)
        mask[0, 0] = 1
        mask[0, 1] = 1
        mask[1, 1] = 1
        mask[5, 0] = 1
        mask[3, 2] = 2
        mask[3, 3] = 2
        mask[4, 3] = 2
        mask[4, 4] = 2

        result = analysis.extract_change_components(mask, min_pixels=2, connectivity=8)
        self.assertEqual(result["all_changed"]["raw_component_count"], 3)
        self.assertEqual(result["all_changed"]["filtered_component_count"], 2)
        self.assertEqual(result["road_change"]["raw_component_count"], 2)
        self.assertEqual(result["road_change"]["filtered_component_count"], 1)
        self.assertEqual(result["building_change"]["filtered_component_count"], 1)

        road = result["road_change"]["items"][0]
        self.assertEqual(road["component_id"], 1)
        self.assertEqual(road["class"], "road_change")
        self.assertEqual(road["class_id"], 1)
        self.assertEqual(road["pixel_area"], 3)
        self.assertEqual(
            road["bounding_box_pixels"],
            {"x_min": 0, "y_min": 0, "x_max_exclusive": 2, "y_max_exclusive": 2},
        )
        self.assertAlmostEqual(road["centroid_pixels"]["x"], 2 / 3)
        self.assertAlmostEqual(road["centroid_pixels"]["y"], 1 / 3)
        self.assertEqual(result["building_change"]["largest_component_pixels"], 4)
        self.assertEqual(result["minimum_component_pixels"], 2)
        self.assertEqual(result["connectivity"], 8)

    def test_four_connectivity_does_not_join_diagonal_pixels(self):
        mask = np.array([[1, 0], [0, 1]], dtype=np.uint8)
        result = analysis.extract_change_components(mask, min_pixels=1, connectivity=4)
        self.assertEqual(result["road_change"]["raw_component_count"], 2)


@unittest.skipIf(analysis is None, "analysis module is not implemented")
class PhysicalAreaTest(unittest.TestCase):
    def test_area_is_unavailable_without_validated_metadata(self):
        area, warning = analysis.physical_area_from_metadata(100, None)
        self.assertEqual(
            area,
            {"physical_area_m2": None, "physical_area_hectares": None, "coordinates": None},
        )
        self.assertIn("validated geospatial transform", warning)

    def test_area_uses_only_validated_projected_metric_pixels(self):
        metadata = {
            "validated": True,
            "crs": "EPSG:32643",
            "is_projected": True,
            "linear_units": "metre",
            "pixel_width": 0.5,
            "pixel_height": -0.5,
        }
        area, warning = analysis.physical_area_from_metadata(20, metadata)
        self.assertEqual(area["physical_area_m2"], 5.0)
        self.assertEqual(area["physical_area_hectares"], 0.0005)
        self.assertIsNone(area["coordinates"])
        self.assertIsNone(warning)


if __name__ == "__main__":
    unittest.main()
