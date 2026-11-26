from __future__ import annotations

import json
import math
import struct
from decimal import Decimal
from typing import Any

SPEC = json.loads(r'''{"specVersion": "1.0", "protocolId": "demo-level", "protocolVersion": "D1", "models": ["DEMO-1"], "inputEncoding": "mixed", "maxPayloadBytes": 256, "documents": [{"id": "bin-doc", "file": "demo-binary-table.csv", "sourceType": "fictional"}, {"id": "json-doc", "file": "demo-json-protocol.json", "sourceType": "fictional"}, {"id": "reg-doc", "file": "demo-modbus-table.csv", "sourceType": "fictional"}], "messages": [{"id": "telemetry", "inputType": "binary", "match": {"offset": 0, "bytes": "01"}, "length": {"exact": 4}, "fields": [{"code": "level", "source": {"documentId": "bin-doc", "location": "row 3"}, "selector": {"offset": 1, "length": 2}, "type": "uint16", "bitWidth": 16, "signed": false, "byteOrder": "big", "wordOrder": "none", "scale": "0.01", "offset": "0", "unit": "m", "unitStatus": "known", "required": true, "confirmed": true}, {"code": "battery", "source": {"documentId": "bin-doc", "location": "row 4"}, "selector": {"offset": 3, "length": 1}, "type": "uint8", "bitWidth": 8, "signed": false, "byteOrder": "big", "wordOrder": "none", "scale": "1", "offset": "0", "unit": "%", "unitStatus": "known", "required": true, "confirmed": true}]}, {"id": "json-telemetry", "inputType": "json", "fields": [{"code": "deviceId", "source": {"documentId": "json-doc", "location": "$.payload.id"}, "selector": {"path": "id"}, "type": "string", "scale": "1", "offset": "0", "unit": null, "unitStatus": "dimensionless", "required": true, "confirmed": true}, {"code": "battery", "source": {"documentId": "json-doc", "location": "$.fields[0]"}, "selector": {"collectionPath": "properties", "matchKey": "name", "matchValue": "batt", "valueKey": "value"}, "type": "integer", "scale": "1", "offset": "0", "unit": "%", "unitStatus": "known", "required": true, "confirmed": true}, {"code": "level", "source": {"documentId": "json-doc", "location": "$.fields[1]"}, "selector": {"collectionPath": "properties", "matchKey": "name", "matchValue": "level", "valueKey": "value"}, "type": "integer", "scale": "0.01", "offset": "0", "unit": "m", "unitStatus": "known", "required": true, "confirmed": true}]}, {"id": "registers", "inputType": "modbus", "match": {"registerType": "holding"}, "fields": [{"code": "counter", "source": {"documentId": "reg-doc", "location": "row 2"}, "selector": {"address": 0, "displayAddress": 40001, "registerCount": 2}, "type": "uint32", "bitWidth": 32, "signed": false, "byteOrder": "big", "wordOrder": "high-first", "scale": "1", "offset": "0", "unit": null, "unitStatus": "dimensionless", "required": true, "confirmed": true, "registerType": "holding"}, {"code": "pressure", "source": {"documentId": "reg-doc", "location": "row 3"}, "selector": {"address": 2, "displayAddress": 40003, "registerCount": 2}, "type": "float32", "bitWidth": 32, "signed": true, "byteOrder": "big", "wordOrder": "high-first", "scale": "1", "offset": "0", "unit": "bar", "unitStatus": "known", "required": false, "confirmed": true, "registerType": "holding"}]}], "mappings": [{"source": "deviceId", "targetPath": "deviceId", "targetType": "string", "conversion": null, "contextSource": null, "required": true, "missing": "error", "contractVersion": "demo-1"}, {"source": "level", "targetPath": "data.levelM", "targetType": "number", "conversion": null, "contextSource": null, "required": true, "missing": "error", "contractVersion": "demo-1"}], "conflicts": []}''')
MISSING = object()


def _diag(code: str, message: str, **where: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **where}


def _result(message: str | None, status: str, properties=None, warnings=None, errors=None):
    return {"protocolId": SPEC["protocolId"], "protocolVersion": SPEC["protocolVersion"], "messageType": message,
            "parseStatus": status, "properties": properties or [], "warnings": warnings or [], "errors": errors or []}


def _path(root: Any, path: str) -> Any:
    value = root
    if path in ("", "$"):
        return value
    for part in path.removeprefix("$.").split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return MISSING
    return value


def _match(message: dict[str, Any], payload: Any, kind: str) -> bool:
    if message["inputType"] != kind:
        return False
    match = message.get("match")
    if not match:
        return True
    if kind == "binary":
        expected = bytes.fromhex(match["bytes"])
        offset = match.get("offset", 0)
        return payload[offset:offset + len(expected)] == expected
    if kind == "json":
        return _path(payload, match.get("path", "$")) == match.get("equals")
    return match.get("registerType", payload.get("registerType")) == payload.get("registerType")


def _scale(field: dict[str, Any], raw: Any, warnings: list[dict[str, Any]]) -> Any:
    if raw in field.get("sentinels", []):
        warnings.append(_diag("FIELD_SENTINEL", "字段原始值为无效哨兵"))
        return None
    if field.get("scale") is None:
        warnings.append(_diag("FIELD_SCALE_UNKNOWN", "字段倍率未知"))
        return None
    if not isinstance(raw, (int, float, Decimal)) or isinstance(raw, bool):
        return raw
    value = Decimal(str(raw)) * Decimal(field["scale"]) + Decimal(field.get("offset") or "0")
    return int(value) if value == value.to_integral() else float(value)


def _property(field: dict[str, Any], raw: Any, warnings: list[dict[str, Any]]) -> dict[str, Any]:
    value = _scale(field, raw, warnings)
    if field.get("unitStatus") == "unknown":
        warnings.append(_diag("FIELD_UNIT_UNKNOWN", "字段单位未知"))
    if field.get("enum") and str(raw) in field["enum"]:
        value = field["enum"][str(raw)]
    return {"code": field["code"], "rawValue": raw, "value": value, "unit": field.get("unit")}


def _binary(payload: bytes) -> dict[str, Any]:
    if len(payload) > SPEC["maxPayloadBytes"]:
        return _result(None, "failed", errors=[_diag("PAYLOAD_TOO_LARGE", "载荷超过规则上限", expected=SPEC["maxPayloadBytes"], actual=len(payload))])
    message = next((m for m in SPEC["messages"] if _match(m, payload, "binary")), None)
    if message is None:
        return _result(None, "failed", errors=[_diag("UNKNOWN_MESSAGE", "无法识别消息类型")])
    exact = message.get("length", {}).get("exact")
    if exact is not None and len(payload) < exact:
        return _result(message["id"], "failed", errors=[_diag("FRAME_TRUNCATED", "报文长度不足", expected=exact, actual=len(payload), byteOffset=len(payload))])
    checksum = message.get("checksum")
    if checksum:
        if checksum["algorithm"] != "xor8":
            return _result(message["id"], "failed", errors=[_diag("CHECKSUM_UNSUPPORTED", "未支持的强制校验算法", actual=checksum["algorithm"])])
        value = checksum["initial"]
        for byte in payload[checksum["start"]:checksum["endExclusive"]]:
            value ^= byte
        if value != payload[checksum["position"]]:
            return _result(message["id"], "failed", errors=[_diag("CHECKSUM_MISMATCH", "校验值不匹配", byteOffset=checksum["position"], expected=value, actual=payload[checksum["position"]])])
    properties, warnings = [], []
    for field in message["fields"]:
        selector = field["selector"]
        start, length = selector["offset"], selector["length"]
        if start + length > len(payload):
            return _result(message["id"], "failed", errors=[_diag("FRAME_TRUNCATED", "字段数据不完整", byteOffset=len(payload), expected=start + length, actual=len(payload))])
        chunk = payload[start:start + length]
        if field["type"] == "float32":
            raw = struct.unpack(">f" if field.get("byteOrder") == "big" else "<f", chunk)[0]
            if not math.isfinite(raw):
                warnings.append(_diag("NON_FINITE_NUMBER", "浮点字段不是有限数", byteOffset=start)); raw = None
        elif field["type"] == "bits":
            base = int.from_bytes(chunk, field.get("byteOrder", "big")); mask = (1 << selector["bitLength"]) - 1
            raw = (base >> selector["bitOffset"]) & mask
        else:
            raw = int.from_bytes(chunk, field.get("byteOrder", "big"), signed=field["type"].startswith("int") or field.get("signed", False))
        properties.append(_property(field, raw, warnings))
    return _result(message["id"], "partial" if warnings else "success", properties, warnings)


def _json(payload: Any) -> dict[str, Any]:
    message = next((m for m in SPEC["messages"] if _match(m, payload, "json")), None)
    if message is None:
        return _result(None, "failed", errors=[_diag("UNKNOWN_MESSAGE", "无法识别 JSON 消息类型")])
    properties, warnings, errors = [], [], []
    for field in message["fields"]:
        selector = field["selector"]
        if "collectionPath" in selector:
            items = _path(payload, selector["collectionPath"])
            matches = [] if not isinstance(items, list) else [x for x in items if isinstance(x, dict) and x.get(selector["matchKey"]) == selector["matchValue"]]
            if len(matches) > 1:
                warnings.append(_diag("DUPLICATE_JSON_FIELD", "数组字段标识重复", jsonPath=selector["collectionPath"]))
            raw = matches[0].get(selector.get("valueKey", "value"), MISSING) if matches else MISSING
        else:
            raw = _path(payload, selector.get("path", "$"))
        if raw is MISSING:
            (errors if field.get("required") and field.get("missing", "error") == "error" else warnings).append(_diag("FIELD_MISSING", "字段缺失", jsonPath=selector.get("path", selector.get("collectionPath", "$"))))
            continue
        expected = field["type"]
        good = ((expected == "string" and isinstance(raw, str)) or (expected == "boolean" and isinstance(raw, bool)) or
                (expected == "integer" and isinstance(raw, int) and not isinstance(raw, bool)) or
                (expected == "number" and isinstance(raw, (int, float)) and not isinstance(raw, bool)))
        if not good:
            warnings.append(_diag("FIELD_TYPE_MISMATCH", "JSON 字段类型不匹配", jsonPath=selector.get("path", "$"), expected=expected, actual=type(raw).__name__))
            continue
        properties.append(_property(field, raw, warnings))
    status = "failed" if errors else "partial" if warnings else "success"
    return _result(message["id"], status, [] if status == "failed" else properties, warnings, errors)


def _modbus(payload: dict[str, Any]) -> dict[str, Any]:
    registers, start = payload.get("registers"), payload.get("startAddress")
    if not isinstance(start, int) or not isinstance(registers, list) or any(not isinstance(x, int) or isinstance(x, bool) or x < 0 or x > 65535 for x in registers):
        return _result(None, "failed", errors=[_diag("REGISTER_VALUE_INVALID", "寄存器输入无效")])
    message = next((m for m in SPEC["messages"] if _match(m, payload, "modbus")), None)
    if message is None:
        return _result(None, "failed", errors=[_diag("UNKNOWN_MESSAGE", "无法识别 Modbus 消息类型")])
    properties, warnings, errors = [], [], []
    for field in message["fields"]:
        selector = field["selector"]; address, count = selector["address"], selector.get("registerCount", 1); index = address - start
        if index < 0 or index + count > len(registers):
            missing = address if index < 0 else start + len(registers)
            (errors if field.get("required") else warnings).append(_diag("REGISTER_MISSING", "寄存器块不完整", registerAddress=missing)); continue
        words = registers[index:index + count]
        if count == 2 and field.get("wordOrder") == "low-first":
            words = list(reversed(words))
        data = b"".join(word.to_bytes(2, field.get("byteOrder", "big")) for word in words)
        if field["type"] == "float32":
            raw = struct.unpack(">f", data)[0]
            if not math.isfinite(raw):
                warnings.append(_diag("NON_FINITE_NUMBER", "浮点字段不是有限数", registerAddress=address)); raw = None
        else:
            raw = int.from_bytes(data, "big", signed=field["type"].startswith("int"))
        properties.append(_property(field, raw, warnings))
    status = "failed" if errors else "partial" if warnings else "success"
    return _result(message["id"], status, [] if status == "failed" else properties, warnings, errors)


def parse(payload: bytes | str | dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    del context
    if isinstance(payload, bytes): return _binary(payload)
    if isinstance(payload, str):
        text = payload.strip()
        if text.startswith(("{", "[")):
            try: return _json(json.loads(text))
            except json.JSONDecodeError as exc: return _result(None, "failed", errors=[_diag("FIELD_TYPE_MISMATCH", "JSON 载荷无效", actual=str(exc))])
        compact = "".join(text.split())
        if len(compact) % 2 or any(char not in "0123456789abcdefABCDEF" for char in compact):
            return _result(None, "failed", errors=[_diag("INVALID_HEX", "HEX 含非法字符或长度为奇数")])
        return _binary(bytes.fromhex(compact))
    if isinstance(payload, dict) and "registers" in payload: return _modbus(payload)
    if isinstance(payload, dict): return _json(payload)
    return _result(None, "failed", errors=[_diag("FIELD_TYPE_MISMATCH", "不支持的输入类型")])


def map_result(result: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}; by_code = {item["code"]: item for item in result["properties"]}; output: dict[str, Any] = {}
    for mapping in SPEC.get("mappings", []):
        source = context.get(mapping.get("contextSource")) if mapping.get("contextSource") else by_code.get(mapping["source"], {}).get("value")
        if source is None and mapping["required"]: return {"ok": False, "error": _diag("MAPPING_REQUIRED_MISSING", "目标映射缺少必填来源", actual=mapping["source"])}
        if source is None and mapping.get("missing") == "omit": continue
        cursor = output; parts = mapping["targetPath"].split(".")
        for part in parts[:-1]: cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = source
    return {"ok": True, "data": output}
