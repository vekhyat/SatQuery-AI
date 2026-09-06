"""Team boundary tests: portable inputs, registry, schemas, URLs, HTTP and isolation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from importlib import resources, util
import json
from pathlib import Path
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from satquery.tools.tool3 import DatasetError, check_tool3_request, optical_sar_v1
from satquery.tools.tool3.artifacts import resolve_artifact, to_web_result
from satquery.tools.tool3.demo import create_demo
from satquery.tools.tool3.evaluation import evaluate_files
from satquery.tools.tool3.inputs import read_json

HAS_API = util.find_spec("fastapi") is not None and util.find_spec("httpx") is not None
HAS_SCHEMA = util.find_spec("jsonschema") is not None


class HandoffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = create_demo(self.root / "scene")
        self.request = read_json(self.manifest)
        self.output = self.root / "output"

    def run_tool(self, request=None):
        return optical_sar_v1(self.request if request is None else request,
                              base_dir=self.manifest.parent, output_dir=self.output)

    def test_registry_handoff_without_working_directory_assumptions(self):
        registry = {"optical_sar_v1": optical_sar_v1}
        before = deepcopy(self.request)
        result = registry["optical_sar_v1"](self.request, base_dir=self.manifest.parent, output_dir=self.output)
        self.assertEqual(self.request, before)
        self.assertEqual(result["task"], "optical_sar")
        self.assertEqual(result["facts"]["sar_added_water_pixels"], 64)
        self.assertEqual(result["facts"]["sar_added_builtup_pixels"], 72)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False))["confidence"], 0.0)
        metrics = evaluate_files(result["overlay"]["file"], self.manifest.parent / "reference.tif")
        self.assertEqual(metrics["accuracy"], 1.0)  # Synthetic software check only.

    def test_checker_is_header_only_and_does_not_write_output(self):
        with patch("satquery.tools.tool3.pipeline.read_aligned", side_effect=AssertionError("pixel access")):
            result = check_tool3_request(self.request, base_dir=self.manifest.parent)
        self.assertEqual(result["status"], "metadata_valid")
        self.assertFalse(self.output.exists())

    def test_malformed_requests_are_structured_rejections(self):
        cases = [None, [], {}, {"bands": {}}, {**self.request, "unknown": 1}]
        for params in (None, [], {"surprise": 1}, {"max_pixels": True}, {"ndwi_threshold": float("nan")}, {"speckle_size": 2}):
            cases.append({**self.request, "parameters": params})
        for value in ("\x00.tif", "", {"path": "green.tif", "band": False}, {"path": "green.tif", "extra": 1}):
            candidate = deepcopy(self.request)
            candidate["bands"]["green"] = value
            cases.append(candidate)
        for request in cases:
            with self.subTest(request=request):
                result = optical_sar_v1(request, base_dir=self.manifest.parent, output_dir=self.output)
                self.assertEqual(result["task"], "reject")
                self.assertTrue(result["receipt"]["rejected"])
                self.assertEqual(result["layers"], {})
                json.dumps(result, allow_nan=False)

    def test_missing_files_and_invalid_output_have_rejection_envelopes(self):
        request = deepcopy(self.request)
        request["bands"]["vv"] = "missing.tif"
        self.assertEqual(self.run_tool(request)["task"], "reject")
        for output in (None, "", "\x00"):
            result = optical_sar_v1(self.request, base_dir=self.manifest.parent, output_dir=output)
            self.assertEqual(result["task"], "reject")

    def test_demo_does_not_overwrite_existing_data(self):
        before = self.manifest.read_bytes()
        with self.assertRaises(FileExistsError):
            create_demo(self.manifest.parent)
        self.assertEqual(self.manifest.read_bytes(), before)

    def test_concurrent_runs_publish_separate_complete_results(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.run_tool(), range(2)))
        for result in results:
            self.assertEqual(result["task"], "optical_sar", result.get("receipt"))
        run_ids = {item["receipt"]["run_id"] for item in results}
        self.assertEqual(len(run_ids), 2)
        for result in results:
            run = Path(result["receipt"]["output_dir"])
            self.assertEqual(read_json(run / "result.json"), result)
            self.assertTrue((run / "report.html").is_file())
        self.assertIn(read_json(self.output / "latest.json")["run_id"], run_ids)
        self.assertFalse(list(self.output.glob(".pending_*")))

    def test_public_urls_are_fetchable_paths_and_original_result_unchanged(self):
        result = self.run_tool()
        before = deepcopy(result)
        web = to_web_result(result, output_dir=self.output, artifact_base_url="https://example.test/tool3/artifacts")
        self.assertEqual(result, before)
        self.assertNotIn("output_dir", web["receipt"])
        self.assertNotIn("inputs", web["receipt"])
        self.assertNotIn(str(self.root), json.dumps(web))
        self.assertEqual(set(web["layers"]), {"optical_only", "sar_only", "fused"})
        for name, url in web["receipt"]["artifacts"].items():
            self.assertTrue(url.endswith("/" + name))
            self.assertTrue(resolve_artifact(self.output, result["receipt"]["run_id"], name).is_file())

    def test_latest_pointer_retries_transient_windows_sharing_error(self):
        original_replace = Path.replace
        attempts = []
        def replace(path, destination):
            if Path(destination).name == "latest.json":
                attempts.append(path)
                if len(attempts) == 1:
                    raise PermissionError("Windows sharing violation")
            return original_replace(path, destination)
        with patch.object(Path, "replace", replace):
            result = self.run_tool()
        self.assertEqual(result["task"], "optical_sar", result.get("receipt"))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(read_json(self.output / "latest.json")["run_id"], result["receipt"]["run_id"])

    def test_artifact_boundary_rejects_private_files_and_traversal(self):
        result = self.run_tool()
        run_id = result["receipt"]["run_id"]
        for run, name in ((run_id, "result.json"), (run_id, "report.html"), (run_id, "../fused.tif"),
                          ("../scene", "fused.tif"), (run_id, "missing.png"), (run_id, None)):
            with self.subTest(run=run, name=name), self.assertRaises(DatasetError):
                resolve_artifact(self.output, run, name)
        (self.output / run_id / "result.json").unlink()
        with self.assertRaises(DatasetError):
            resolve_artifact(self.output, run_id, "fused.tif")

    def test_public_result_rejects_wrong_root_and_invalid_url(self):
        result = self.run_tool()
        with self.assertRaises(DatasetError):
            to_web_result(result, output_dir=self.root / "wrong")
        for base in ("javascript:alert(1)", "//example.test", "relative", "/files?key=a", "/files#fragment"):
            with self.subTest(base=base), self.assertRaises(DatasetError):
                to_web_result(result, output_dir=self.output, artifact_base_url=base)

    @unittest.skipUnless(HAS_SCHEMA, "Install .[test] to validate JSON schemas")
    def test_success_rejection_and_public_response_match_packaged_schemas(self):
        from jsonschema import Draft202012Validator
        request_schema = json.loads(resources.files("satquery.tools.tool3").joinpath("schemas/request.schema.json").read_text())
        result_schema = json.loads(resources.files("satquery.tools.tool3").joinpath("schemas/result.schema.json").read_text())
        for schema in (request_schema, result_schema):
            Draft202012Validator.check_schema(schema)
        Draft202012Validator(request_schema).validate(self.request)
        result = self.run_tool()
        validator = Draft202012Validator(result_schema)
        for response in (result, self.run_tool({}), to_web_result(result, output_dir=self.output)):
            validator.validate(response)
        malformed = deepcopy(result)
        del malformed["layers"]["sar_only"]
        self.assertFalse(validator.is_valid(malformed))


@unittest.skipUnless(HAS_API, "Install .[test] for HTTP integration tests")
class HttpTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from satquery.tools.tool3.http_api import create_app
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.manifest = create_demo(self.root / "scene")
        self.output = self.root / "results"
        self.app = create_app(self.manifest.parent / "catalog.json", self.output, max_pixels=4096)
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def test_http_full_run_and_all_three_layer_downloads(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        response = self.client.post("/tools/optical_sar_v1", json={"dataset_id": "synthetic"})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertNotIn(str(self.root), response.text)
        for url in result["layers"].values():
            image = self.client.get(url)
            self.assertEqual(image.status_code, 200)
            self.assertTrue(image.content.startswith(b"\x89PNG"))
        overlay = self.client.get(result["overlay"]["file"])
        self.assertEqual(overlay.status_code, 200)
        self.assertEqual(overlay.headers["content-type"], "image/tiff")
        run_id = result["receipt"]["run_id"]
        self.assertEqual(self.client.get(f"/artifacts/{run_id}/result.json").status_code, 404)
        self.assertEqual(self.client.get(f"/artifacts/{run_id}/report.html").status_code, 404)

    def test_http_rejects_unknown_datasets_paths_and_invalid_parameters(self):
        for body, status in (({}, 404), ({"dataset_id": "unknown"}, 404),
                             ({"dataset_id": "synthetic", "bands": {}}, 422),
                             ({"dataset_id": "synthetic", "parameters": []}, 422),
                             ({"dataset_id": "synthetic", "parameters": {"max_pixels": True}}, 422),
                             ({"dataset_id": "synthetic", "parameters": {"max_pixels": 4097}}, 422),
                             ({"dataset_id": "synthetic", "parameters": {"unknown": 1}}, 422)):
            with self.subTest(body=body):
                response = self.client.post("/tools/optical_sar_v1", json=body)
                self.assertEqual(response.status_code, status)
                self.assertTrue(response.json()["receipt"]["rejected"])
        self.assertFalse(self.output.exists())

    def test_invalid_json_and_array_body_return_shared_envelope(self):
        for content in ("{broken", "[]", "null"):
            response = self.client.post("/tools/optical_sar_v1", content=content, headers={"Content-Type": "application/json"})
            self.assertEqual(response.status_code, 422)
            self.assertEqual(response.json()["task"], "reject")

    def test_http_data_failure_hides_local_paths(self):
        (self.manifest.parent / "vv.tif").unlink()
        response = self.client.post("/tools/optical_sar_v1", json={"dataset_id": "synthetic"})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(str(self.root), response.text)
        self.assertEqual(response.json()["layers"], {})

    def test_unexpected_worker_error_is_500_and_slot_is_released(self):
        with patch("satquery.tools.tool3.http_api.optical_sar_v1", side_effect=RuntimeError("private/path")):
            response = self.client.post("/tools/optical_sar_v1", json={"dataset_id": "synthetic"})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("private/path", response.text)
        self.assertEqual(self.client.post("/tools/optical_sar_v1", json={"dataset_id": "synthetic"}).status_code, 200)

    def test_busy_worker_is_bounded_and_returns_retry_after(self):
        started, release = Event(), Event()
        from satquery.tools.tool3.contracts import rejection
        def slow(*args, **kwargs):
            started.set()
            if not release.wait(10):
                raise RuntimeError("Test did not release worker")
            return rejection("test rejection")
        with patch("satquery.tools.tool3.http_api.optical_sar_v1", side_effect=slow), ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(self.client.post, "/tools/optical_sar_v1", json={"dataset_id": "synthetic"})
            try:
                self.assertTrue(started.wait(10))
                response = self.client.post("/tools/optical_sar_v1", json={"dataset_id": "synthetic"})
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.headers["Retry-After"], "5")
            finally:
                release.set()
            self.assertEqual(first.result().status_code, 422)


if __name__ == "__main__":
    unittest.main()
