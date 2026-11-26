import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location("device_protocol", ROOT / "scripts/device_protocol.py")
module = importlib.util.module_from_spec(loader)
loader.loader.exec_module(module)


class ToolTest(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / "examples/demo-binary-spec.json").read_text(encoding="utf-8"))

    def test_demo_spec_valid(self):
        errors, warnings = module.validate_spec(self.spec)
        self.assertEqual([], errors)
        self.assertEqual([], warnings)

    def test_overlap_and_mapping_collision_rejected(self):
        field = dict(self.spec["messages"][0]["fields"][0])
        field["code"] = "overlap"
        self.spec["messages"][0]["fields"].append(field)
        self.spec["mappings"].append(dict(self.spec["mappings"][0]))
        errors, _ = module.validate_spec(self.spec)
        self.assertTrue(any("FIELD_OVERLAP" in item for item in errors))
        self.assertTrue(any("MAPPING_COLLISION" in item for item in errors))

    def test_csv_extraction_keeps_cells(self):
        evidence = module.extract_text(ROOT / "examples/demo-modbus-table.csv")
        self.assertTrue(any(item["location"] == "row 2 cell 2" and item["text"] == "0" for item in evidence["records"]))
        self.assertEqual(64, len(evidence["sha256"]))

    def test_generator_changes_with_rule(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "a"; second = Path(directory) / "b"
            module.generate_python(self.spec, first)
            self.spec["messages"][0]["fields"][0]["scale"] = "0.1"
            module.generate_python(self.spec, second)
            self.assertNotEqual((first / "protocol-spec.json").read_text(), (second / "protocol-spec.json").read_text())
            self.assertIn('"scale": "0.1"', (second / "protocol-spec.json").read_text())


if __name__ == "__main__":
    unittest.main()
