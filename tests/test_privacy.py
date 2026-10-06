import copy
import json
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from videomate.demo import SYNTHETIC_KEY, run_demo
from videomate.diagnostics import ExportScope, create_export, environment
from videomate.errors import VideoMateError
from videomate.schema import encode_export, get_schema, load_json, validate_export

ROOT = Path(__file__).resolve().parents[1]


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads((ROOT / "examples/diagnostic-export.synthetic.json").read_text())

    def test_design_example_validates(self):
        validate_export(self.example)

    def test_packaged_schema_matches_design(self):
        self.assertEqual(get_schema(), json.loads((ROOT / "schemas/diagnostic-export-v1.schema.json").read_text()))

    def test_unknown_field_at_every_object_is_rejected(self):
        def walk(value):
            if isinstance(value, dict):
                value["private_filename"] = "SYNTHETIC_CANARY"
                with self.assertRaises(VideoMateError):
                    validate_export(self.example)
                value.pop("private_filename")
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(self.example)

    def test_invalid_diagnostic_values(self):
        for mutate in (
            lambda d: d["environment"].update(app_version="1.2.3\n"),
            lambda d: d["files"][0]["streams"][0].update(codec="PRIVATE_CODEC"),
            lambda d: d["files"][0]["findings"][0].update(category="PRIVATE_ERROR"),
            lambda d: d["files"][0].update(file_ref="f_PRIVATE_NAME"),
            lambda d: d.update(schema_version=True),
        ):
            candidate = copy.deepcopy(self.example)
            mutate(candidate)
            with self.assertRaises(VideoMateError):
                encode_export(candidate)

    def test_semantic_constraints(self):
        for mutate in (
            lambda d: d["files"][0]["findings"][0]["interval"].update(start_us=999999999),
            lambda d: d["files"].append(copy.deepcopy(d["files"][0])),
            lambda d: d["files"][0]["streams"][1].update(index=0),
            lambda d: d["files"][0]["streams"][0].update(kind="audio"),
            lambda d: d["files"][0]["verification"].update(decode_check="inconclusive"),
            lambda d: d["files"][0].update(scan_depth="quick", integrity="no_errors_detected"),
            lambda d: d["files"][0]["findings"][0].update(stream_index=123),
        ):
            candidate = copy.deepcopy(self.example)
            mutate(candidate)
            with self.assertRaises(VideoMateError):
                validate_export(candidate)

    def test_json_limits_duplicates_and_nonfinite(self):
        for data in (b'{"x":1,"x":2}', b'NaN', b'Infinity', b'1e309', b'{} trailing', b'[' * 40 + b']' * 40):
            with self.assertRaises(VideoMateError):
                load_json(data)
        with self.assertRaises(VideoMateError):
            load_json(b'{}', limit=1)

    def test_hmac_scoping_domain_separation_and_private_ids(self):
        record = UUID(int=1)
        a = ExportScope(SYNTHETIC_KEY, bytes(16))
        same = ExportScope(SYNTHETIC_KEY, bytes(16))
        b = ExportScope(SYNTHETIC_KEY, bytes([1]) * 16)
        changed_key = ExportScope(bytes([2]) * 32, bytes(16))
        self.assertEqual(a.reference("file", record), same.reference("file", record))
        self.assertNotEqual(a.reference("file", record), b.reference("file", record))
        self.assertNotEqual(a.reference("file", record), changed_key.reference("file", record))
        self.assertNotEqual(a.reference("file", record)[2:], a.reference("job", record)[2:])
        self.assertNotIn(str(record), a.reference("file", record))
        with self.assertRaises(VideoMateError):
            ExportScope(b"short")

    def test_synthetic_demo_has_no_canary_or_private_identity(self):
        results, encoded = run_demo()
        self.assertNotIn(b'SYNTHETIC_PRIVATE', encoded)
        self.assertNotIn(b'generated-marker', encoded)
        self.assertNotIn(b'tags', encoded)
        for result in results:
            self.assertNotIn(str(result.input_id).encode(), encoded)
        parsed = load_json(encoded)
        validate_export(parsed)
        self.assertEqual(parsed["data_origin"], "synthetic_example")

    def test_fresh_export_scopes(self):
        results, _ = run_demo()
        job = uuid4()
        args = (results, job, SYNTHETIC_KEY, environment("0.0.0", "0.0.0"))
        a, b = load_json(create_export(*args)), load_json(create_export(*args))
        self.assertNotEqual(a["export_scope"], b["export_scope"])
        self.assertNotEqual(a["files"][0]["file_ref"], b["files"][0]["file_ref"])

    def test_reference_jsonschema_validator_when_available(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Optional reference validator is not installed; no download attempted")
        jsonschema.Draft202012Validator.check_schema(get_schema())
        _, encoded = run_demo()
        jsonschema.Draft202012Validator(get_schema()).validate(load_json(encoded))
