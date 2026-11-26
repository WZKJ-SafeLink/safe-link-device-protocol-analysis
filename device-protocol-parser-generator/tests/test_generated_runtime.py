import json
import math
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "examples/demo-binary-spec.json").read_text(encoding="utf-8"))
TEMPLATE = (ROOT / "templates/python-parser.tpl").read_text(encoding="utf-8")


def runtime(spec):
    namespace = {}
    exec(TEMPLATE.replace("__SPEC_JSON__", json.dumps(spec, ensure_ascii=False)), namespace)
    return namespace


class GeneratedRuntimeTest(unittest.TestCase):
    def test_unknown_scale_preserves_raw(self):
        spec = json.loads(json.dumps(BASE)); spec["messages"] = [spec["messages"][0]]
        spec["messages"][0]["fields"][0]["scale"] = None
        result = runtime(spec)["parse"]("01 02 58 5F")
        self.assertEqual("partial", result["parseStatus"])
        self.assertEqual(600, result["properties"][0]["rawValue"])
        self.assertIsNone(result["properties"][0]["value"])
        self.assertIn("FIELD_SCALE_UNKNOWN", [item["code"] for item in result["warnings"]])

    def test_xor_checksum_pass_and_fail(self):
        spec = json.loads(json.dumps(BASE)); message = spec["messages"][0]; spec["messages"] = [message]
        message["length"]["exact"] = 5; message["checksum"] = {"algorithm":"xor8","start":0,"endExclusive":4,"position":4,"initial":0,"required":True}
        parse = runtime(spec)["parse"]
        self.assertEqual("success", parse("01 02 58 5F 04")["parseStatus"])
        failed = parse("01 02 58 5F 05")
        self.assertEqual("failed", failed["parseStatus"])
        self.assertEqual([], failed["properties"])
        self.assertEqual("CHECKSUM_MISMATCH", failed["errors"][0]["code"])

    def test_signed_and_sentinel_before_scale(self):
        spec = json.loads(json.dumps(BASE)); field = spec["messages"][0]["fields"][0]
        spec["messages"] = [spec["messages"][0]]; spec["messages"][0]["length"]["exact"] = 3; spec["messages"][0]["fields"] = [field]
        field.update({"code":"temperature","type":"int16","signed":True,"scale":"0.1","unit":"C","sentinels":[-32768]})
        parse = runtime(spec)["parse"]
        value = parse("01 FF 9C")["properties"][0]
        self.assertEqual(-100, value["rawValue"]); self.assertEqual(-10, value["value"])
        sentinel = parse("01 80 00")
        self.assertIsNone(sentinel["properties"][0]["value"])
        self.assertEqual("FIELD_SENTINEL", sentinel["warnings"][0]["code"])

    def test_low_word_order_and_nonfinite_float(self):
        spec = json.loads(json.dumps(BASE)); message = spec["messages"][2]; spec["messages"] = [message]
        message["fields"][0]["wordOrder"] = "low-first"; message["fields"] = [message["fields"][0]]
        parse = runtime(spec)["parse"]
        self.assertEqual(131073, parse({"registerType":"holding","startAddress":0,"registers":[1,2]})["properties"][0]["value"])
        field = json.loads(json.dumps(BASE["messages"][2]["fields"][1])); field["selector"]["address"] = 0; message["fields"] = [field]
        value = runtime(spec)["parse"]({"registerType":"holding","startAddress":0,"registers":[0x7F80,0]})
        self.assertEqual("partial", value["parseStatus"]); self.assertIsNone(value["properties"][0]["rawValue"])

    def test_json_order_type_and_mapping_failure(self):
        parse = runtime(BASE)["parse"]
        one = parse({"id":"00123","properties":[{"name":"level","value":600},{"name":"batt","value":95}]})
        self.assertEqual("00123", one["properties"][0]["value"])
        wrong = parse({"id":"00123","properties":[{"name":"level","value":"600"},{"name":"batt","value":True}]})
        self.assertEqual("partial", wrong["parseStatus"])
        mapping = runtime(BASE)["map_result"](parse({"properties":[]}), {})
        self.assertFalse(mapping["ok"]); self.assertEqual("MAPPING_REQUIRED_MISSING", mapping["error"]["code"])

    def test_illegal_hex_and_unseen_offset(self):
        module = runtime(BASE); self.assertEqual("INVALID_HEX", module["parse"]("0Z1")["errors"][0]["code"])
        spec = json.loads(json.dumps(BASE)); message = spec["messages"][0]; spec["messages"] = [message]
        message["length"]["exact"] = 6; message["fields"] = [message["fields"][1]]; message["fields"][0]["code"] = "signal"; message["fields"][0]["selector"]["offset"] = 5
        result = runtime(spec)["parse"]("01 00 00 00 00 2A")
        self.assertEqual(42, result["properties"][0]["value"])


if __name__ == "__main__": unittest.main()
