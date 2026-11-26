#!/usr/bin/env python3
"""Offline protocol-spec validator, source generator, replay runner, and packager."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
PROTOCOL_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
JAVA_PACKAGE = re.compile(r"^[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)*$")


class UserError(Exception):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UserError(f"无法读取 JSON {path}: {exc}") from exc


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_spec(spec: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    required = ["specVersion", "protocolId", "protocolVersion", "models", "inputEncoding", "maxPayloadBytes", "documents", "messages", "mappings"]
    for key in required:
        if key not in spec:
            errors.append(f"SPEC_REQUIRED: 缺少 {key}")
    if errors:
        return errors, warnings
    if spec["specVersion"] != "1.0": errors.append("SPEC_VERSION: 仅支持 specVersion 1.0")
    if not isinstance(spec["protocolId"], str) or not PROTOCOL_ID.fullmatch(spec["protocolId"]): errors.append("PROTOCOL_ID: protocolId 非法")
    if not isinstance(spec["maxPayloadBytes"], int) or spec["maxPayloadBytes"] <= 0: errors.append("PAYLOAD_LIMIT: maxPayloadBytes 必须为正整数")
    document_ids = {doc.get("id") for doc in spec.get("documents", [])}
    message_ids: set[str] = set()
    match_keys: set[str] = set()
    for mi, message in enumerate(spec.get("messages", [])):
        prefix = f"messages[{mi}]"
        mid = message.get("id")
        if not isinstance(mid, str) or not IDENT.fullmatch(mid): errors.append(f"MESSAGE_ID: {prefix}.id 非法")
        if mid in message_ids: errors.append(f"MESSAGE_DUPLICATE: 重复消息 {mid}")
        message_ids.add(mid)
        kind = message.get("inputType")
        if kind not in {"binary", "json", "modbus"}: errors.append(f"MESSAGE_TYPE: {prefix}.inputType 非法")
        match_key = json.dumps([kind, message.get("match")], sort_keys=True, ensure_ascii=False)
        if match_key in match_keys: errors.append(f"MESSAGE_MATCH_COLLISION: {mid} 与同级消息判别条件冲突")
        match_keys.add(match_key)
        fields = message.get("fields")
        if not isinstance(fields, list): errors.append(f"FIELDS: {prefix}.fields 必须为数组"); continue
        codes: set[str] = set(); occupied: list[tuple[int, int, str, bool]] = []
        for fi, field in enumerate(fields):
            fp = f"{prefix}.fields[{fi}]"; code = field.get("code")
            if not isinstance(code, str) or not IDENT.fullmatch(code): errors.append(f"FIELD_CODE: {fp}.code 非法")
            if code in codes: errors.append(f"FIELD_DUPLICATE: 消息 {mid} 重复字段 {code}")
            codes.add(code)
            source = field.get("source", {})
            if source.get("documentId") not in document_ids: errors.append(f"SOURCE_UNKNOWN: {fp} 引用了未知文档")
            if not source.get("location"): errors.append(f"SOURCE_LOCATION: {fp} 缺少来源位置")
            if field.get("scale", "missing") == "missing": errors.append(f"SCALE_REQUIRED: {fp} 必须显式写 scale，未知写 null")
            if field.get("unitStatus") not in {"known", "unknown", "dimensionless"}: errors.append(f"UNIT_STATUS: {fp} unitStatus 非法")
            if not field.get("confirmed", False): warnings.append(f"FIELD_UNCONFIRMED: {mid}.{code} 尚未确认")
            selector = field.get("selector", {})
            if kind == "binary":
                start, length = selector.get("offset"), selector.get("length")
                if not isinstance(start, int) or start < 0 or not isinstance(length, int) or length <= 0: errors.append(f"BINARY_SELECTOR: {fp} 偏移或长度非法")
                else:
                    for other_start, other_end, other_code, shared in occupied:
                        if start < other_end and start + length > other_start and not (shared and field.get("sharedBits", False)):
                            errors.append(f"FIELD_OVERLAP: {mid}.{code} 与 {other_code} 无意重叠")
                    occupied.append((start, start + length, code, field.get("sharedBits", False)))
            elif kind == "json" and not ("path" in selector or "collectionPath" in selector): errors.append(f"JSON_SELECTOR: {fp} 缺少路径")
            elif kind == "modbus":
                if not isinstance(selector.get("address"), int) or selector.get("address", -1) < 0: errors.append(f"REGISTER_ADDRESS: {fp} 实际地址非法")
                if field.get("wordOrder") == "unknown": warnings.append(f"WORD_ORDER_UNKNOWN: {mid}.{code} 字序待确认")
        checksum = message.get("checksum")
        if checksum and checksum.get("algorithm") != "xor8": warnings.append(f"CHECKSUM_UNSUPPORTED: {mid} 使用未实现的 {checksum.get('algorithm')}")
    paths: set[str] = set()
    for index, mapping in enumerate(spec.get("mappings", [])):
        path = mapping.get("targetPath")
        if not isinstance(path, str) or not IDENT.fullmatch(path): errors.append(f"MAPPING_PATH: mappings[{index}] 目标路径非法")
        if path in paths: errors.append(f"MAPPING_COLLISION: 映射路径重复 {path}")
        paths.add(path)
    for conflict in spec.get("conflicts", []):
        if not conflict.get("resolution"): warnings.append(f"EVIDENCE_CONFLICT: {conflict.get('id')} 尚未解决，影响 {', '.join(conflict.get('affected', []))}")
    return errors, warnings


def assert_output_available(output: Path) -> None:
    if output.exists() and any(output.iterdir() if output.is_dir() else [output]):
        raise UserError(f"输出路径已存在且非空，拒绝覆盖: {output}")


def atomic_generate(output: Path, producer) -> None:
    assert_output_available(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        producer(temp)
        if output.exists(): output.rmdir()
        os.replace(temp, output)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise


def copy_contract_files(target: Path, spec: dict[str, Any]) -> None:
    dump_json(target / "protocol-spec.json", spec)
    shutil.copy2(ROOT / "references/result.schema.json", target / "result.schema.json")
    shutil.copy2(ROOT / "references/error.schema.json", target / "error.schema.json")
    sources = [{"message": m["id"], "field": f["code"], **f["source"]} for m in spec["messages"] for f in m["fields"]]
    dump_json(target / "field-sources.json", sources)


def generate_python(spec: dict[str, Any], target: Path) -> None:
    package = target / "protocol_parser"; tests = target / "tests"; package.mkdir(parents=True); tests.mkdir()
    template = (ROOT / "templates/python-parser.tpl").read_text(encoding="utf-8")
    source = template.replace("__SPEC_JSON__", json.dumps(spec, ensure_ascii=False).replace("'''", "'\\''"))
    (package / "parser.py").write_text(source, encoding="utf-8")
    (package / "__init__.py").write_text("from .parser import parse, map_result\n__all__ = ['parse', 'map_result']\n", encoding="utf-8")
    (package / "__main__.py").write_text("from parser_cli import main\nraise SystemExit(main())\n", encoding="utf-8")
    (target / "parser_cli.py").write_text('''#!/usr/bin/env python3
import argparse, json, sys
from protocol_parser import parse, map_result
def main():
    p=argparse.ArgumentParser(); g=p.add_mutually_exclusive_group(required=True); g.add_argument("--hex"); g.add_argument("--json"); g.add_argument("--modbus"); p.add_argument("--mapped",action="store_true"); a=p.parse_args()
    payload=a.hex if a.hex is not None else json.loads(a.json if a.json is not None else a.modbus)
    result=parse(payload, {}); output=map_result(result,{}) if a.mapped else result
    print(json.dumps(output,ensure_ascii=False,separators=(",",":"),allow_nan=False)); return 0 if result["parseStatus"]!="failed" else 2
if __name__ == "__main__": raise SystemExit(main())
''', encoding="utf-8")
    os.chmod(target / "parser_cli.py", 0o755)
    (target / "pyproject.toml").write_text(f'''[build-system]\nrequires = ["setuptools>=65.5.0,<66", "wheel==0.41.2"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "{spec['protocolId']}-parser"\nversion = "1.0.0"\nrequires-python = ">=3.11"\ndependencies = []\n\n[project.scripts]\ndevice-parser = "parser_cli:main"\n\n[tool.setuptools]\npy-modules = ["parser_cli"]\n\n[tool.setuptools.packages.find]\ninclude = ["protocol_parser*"]\n''', encoding="utf-8")
    (tests / "test_parser.py").write_text('''import unittest\nfrom protocol_parser import parse\nclass ParserTest(unittest.TestCase):\n    def test_unknown(self): self.assertEqual("failed", parse("FF")["parseStatus"])\nif __name__ == "__main__": unittest.main()\n''', encoding="utf-8")
    (target / "README.md").write_text("# Python 设备解析器\n\n要求 Python 3.11+，运行时无第三方依赖；构建固定使用 setuptools 65.5.x 和 wheel 0.41.2。预先缓存构建依赖后可离线安装。\n\n```bash\npython3 -m pip install .\npython3 -m unittest discover -s tests\npython3 parser_cli.py --hex '01 02 58 5F'\npython3 -m protocol_parser --json '{\"id\":\"00123\",\"properties\":[]}'\n```\n\nCLI stdout 仅输出 JSON；解析失败退出码 2，工具参数错误由 argparse 返回 2。公开入口：`protocol_parser.parse(payload, context)`。\n", encoding="utf-8")
    copy_contract_files(target, spec)


def java_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")


def generate_java(spec: dict[str, Any], target: Path, package_name: str) -> None:
    package_path = Path(*package_name.split(".")); main = target / "src/main/java" / package_path; test = target / "src/test/java" / package_path
    main.mkdir(parents=True); test.mkdir(parents=True)
    template = (ROOT / "templates/java-parser.tpl").read_text(encoding="utf-8")
    compact = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
    source = template.replace("__PACKAGE__", package_name).replace("__SPEC_JSON_JAVA__", java_escape(compact))
    (main / "DeviceParser.java").write_text(source, encoding="utf-8")
    (main / "ParserCli.java").write_text(f'''package {package_name};
import java.io.*; import java.nio.charset.StandardCharsets; import java.util.*;
public final class ParserCli {{ public static void main(String[] args) throws Exception {{
String mode=args.length>0?args[0]:"--hex"; String input=new String(System.in.readAllBytes(),StandardCharsets.UTF_8).trim(); Object payload=input;
if("--json".equals(mode)||"--modbus".equals(mode)) payload=DeviceParser.Json.parse(input);
Map<String,Object> result=DeviceParser.parse(payload,Map.of()); System.out.println(DeviceParser.toJson(result)); if("failed".equals(result.get("parseStatus"))) System.exit(2);
}} }}
''', encoding="utf-8")
    (test / "DeviceParserTest.java").write_text(f'''package {package_name};
import org.junit.jupiter.api.Test; import java.util.*; import static org.junit.jupiter.api.Assertions.*;
class DeviceParserTest {{ @Test void unknownMessageFails() {{ assertEquals("failed",DeviceParser.parse("FF",Map.of()).get("parseStatus")); }} }}
''', encoding="utf-8")
    (target / "pom.xml").write_text(f'''<project xmlns="http://maven.apache.org/POM/4.0.0" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
<modelVersion>4.0.0</modelVersion><groupId>{package_name}</groupId><artifactId>{spec['protocolId']}-parser</artifactId><version>1.0.0</version>
<properties><maven.compiler.release>17</maven.compiler.release><project.build.sourceEncoding>UTF-8</project.build.sourceEncoding><junit.version>5.10.2</junit.version></properties>
<dependencies><dependency><groupId>org.junit.jupiter</groupId><artifactId>junit-jupiter</artifactId><version>${{junit.version}}</version><scope>test</scope></dependency></dependencies>
<build><plugins><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-compiler-plugin</artifactId><version>3.13.0</version></plugin><plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId><version>3.2.5</version></plugin></plugins></build></project>
''', encoding="utf-8")
    (target / "README.md").write_text(f"# Java 17 设备解析器\n\n```bash\nmvn -q test\nprintf '01 02 58 5F\\n' | java -cp target/classes {package_name}.ParserCli --hex\nprintf '{{\\\"registerType\\\":\\\"holding\\\",\\\"startAddress\\\":0,\\\"registers\\\":[1,2]}}\\n' | java -cp target/classes {package_name}.ParserCli --modbus\n```\n\n运行时仅依赖 JDK。公开入口：`DeviceParser.parse(payload, context)`。CLI stdout 仅输出 JSON；业务解析失败退出码 2。\n", encoding="utf-8")
    copy_contract_files(target, spec)


def manifest(target: Path, spec: dict[str, Any], language: str, entry: str) -> None:
    dump_json(target / "manifest.json", {"language": language, "languageVersion": "17" if language == "java" else "3.11", "protocolId": spec["protocolId"], "protocolVersion": spec["protocolVersion"], "specVersion": spec["specVersion"], "entry": entry, "buildStatus": "generated", "limitations": ["Safe Link 真实 Schema 与平台导入待客户试点"]})
    (target / "pending-confirmations.md").write_text("# 厂家待确认事项\n\n" + ("\n".join(f"- {w}" for w in validate_spec(spec)[1]) or "- 无规则级待确认项；真实厂家协议仍需试点。") + "\n", encoding="utf-8")


def command_generate(args: argparse.Namespace) -> None:
    spec = load_json(Path(args.spec)); errors, warnings = validate_spec(spec)
    if errors: raise UserError("规则检查失败:\n" + "\n".join(errors))
    output = Path(args.output).resolve()
    if args.language == "java" and not JAVA_PACKAGE.fullmatch(args.package): raise UserError("Java 包名非法")
    def produce(temp: Path) -> None:
        if args.language == "python": generate_python(spec, temp); entry = "protocol_parser.parse"
        else: generate_java(spec, temp, args.package); entry = f"{args.package}.DeviceParser.parse"
        manifest(temp, spec, args.language, entry)
    atomic_generate(output, produce)
    print(json.dumps({"status":"generated","output":str(output),"warnings":warnings}, ensure_ascii=False))


def extract_text(path: Path) -> dict[str, Any]:
    suffix = path.suffix.lower(); records: list[dict[str, Any]] = []
    if suffix in {".txt", ".md", ".json"}:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1): records.append({"location":f"line {number}","text":line})
    elif suffix == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as stream:
            for row_number, row in enumerate(csv.reader(stream), 1):
                for col, value in enumerate(row, 1): records.append({"location":f"row {row_number} cell {col}","text":value})
    elif suffix == ".docx":
        with zipfile.ZipFile(path) as archive: root=ElementTree.fromstring(archive.read("word/document.xml"))
        ns={"w":"http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        for number, paragraph in enumerate(root.findall(".//w:p",ns),1): records.append({"location":f"paragraph {number}","text":"".join(node.text or "" for node in paragraph.findall(".//w:t",ns))})
    elif suffix == ".xlsx":
        with zipfile.ZipFile(path) as archive:
            shared=[]
            if "xl/sharedStrings.xml" in archive.namelist():
                root=ElementTree.fromstring(archive.read("xl/sharedStrings.xml")); shared=["".join(n.text or "" for n in item.iter() if n.tag.endswith("}t")) for item in root]
            for sheet_name in sorted(n for n in archive.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")):
                root=ElementTree.fromstring(archive.read(sheet_name))
                for cell in (node for node in root.iter() if node.tag.endswith("}c")):
                    value=next((n.text for n in cell if n.tag.endswith("}v")),"")
                    if cell.attrib.get("t")=="s" and value: value=shared[int(value)]
                    records.append({"location":f"{Path(sheet_name).stem}!{cell.attrib.get('r','?')}","text":value})
    elif suffix == ".pdf":
        tool=shutil.which("pdftotext")
        if not tool: raise UserError("PDF_TEXT_TOOL_MISSING: 未安装 pdftotext，请使用宿主附件读取或提供 OCR 文本")
        run=subprocess.run([tool,"-layout",str(path),"-"],capture_output=True,text=True,timeout=60,check=False)
        if run.returncode: raise UserError(f"PDF_TEXT_FAILED: {run.stderr.strip()}")
        for page_number,page in enumerate(run.stdout.split("\f"),1):
            for line_number,line in enumerate(page.splitlines(),1): records.append({"location":f"page {page_number} line {line_number}","text":line})
    else: raise UserError(f"不支持的附件类型: {suffix}")
    return {"file":path.name,"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"records":records,"security":"data-only; macros, formulas and embedded code were not executed"}


def normalize_expected(result: dict[str, Any]) -> dict[str, Any]:
    return {"parseStatus":result.get("parseStatus"),"messageType":result.get("messageType"),"properties":{p["code"]:{"rawValue":p.get("rawValue"),"value":p.get("value"),"unit":p.get("unit")} for p in result.get("properties",[])},"errorCodes":[e["code"] for e in result.get("errors",[])]}


def run_vector(project: Path, language: str, vector: dict[str, Any]) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    kind=vector["payloadKind"]; payload=vector["payload"]
    if language == "python":
        arg="--hex" if kind=="hex" else "--json" if kind=="json" else "--modbus"; command=[sys.executable,"parser_cli.py",arg,json.dumps(payload,ensure_ascii=False) if kind!="hex" else payload]
    else:
        arg="--hex" if kind=="hex" else "--json" if kind=="json" else "--modbus"; package=next((project/"src/main/java").glob("**/ParserCli.java")).parent.relative_to(project/"src/main/java").as_posix().replace("/",".")
        command=["java","-cp","target/classes",f"{package}.ParserCli",arg]
    run=subprocess.run(command,cwd=project,input=(json.dumps(payload,ensure_ascii=False) if kind!="hex" else str(payload))+"\n",capture_output=True,text=True,timeout=30,check=False)
    return run, command


def command_replay(args: argparse.Namespace) -> None:
    project=Path(args.project).resolve(); vectors=load_json(Path(args.vectors)); entries=[]
    if args.language=="java":
        build=subprocess.run(["mvn","-q","-DskipTests","compile"],cwd=project,capture_output=True,text=True,timeout=180,check=False)
        if build.returncode: raise UserError("Java 构建失败:\n"+build.stderr[-4000:])
    for vector in vectors:
        run, command=run_vector(project,args.language,vector); actual=None; differences=[]
        try: actual=json.loads(run.stdout)
        except json.JSONDecodeError: differences.append("stdout 不是合法 JSON")
        if actual is not None and normalize_expected(actual)!=vector["expected"]: differences.append("实际结果与封存预期不同")
        entries.append({"id":vector["id"],"inputSource":"examples/demo-vectors.json","expectedSource":vector.get("expectedSource"),"sourceGenerated":"passed","programExecuted":"passed" if actual is not None else "failed","independentExpectedMatched":"passed" if not differences else "failed","command":command,"exitCode":run.returncode,"expected":vector["expected"],"actual":normalize_expected(actual) if actual else None,"differences":differences})
    report={"language":args.language,"generatedAt":datetime.now(timezone.utc).isoformat(),"summary":{"total":len(entries),"passed":sum(e["independentExpectedMatched"]=="passed" for e in entries),"failed":sum(e["independentExpectedMatched"]=="failed" for e in entries)},"entries":entries}
    dump_json(Path(args.report),report); print(json.dumps(report["summary"],ensure_ascii=False))
    if report["summary"]["failed"]: raise SystemExit(1)


def zip_tree(source: Path, output: Path, include_root: bool=False) -> None:
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_dir() or any(part in {"__pycache__","target",".git",".DS_Store"} for part in path.parts): continue
            relative=path.relative_to(source); archive.write(path,(Path(source.name)/relative if include_root else relative).as_posix())


def command_deliver(args: argparse.Namespace) -> None:
    project=Path(args.project).resolve(); stage=Path(tempfile.mkdtemp(prefix="protocol-delivery-"))
    try:
        shutil.copytree(project,stage/"project",dirs_exist_ok=True,ignore=shutil.ignore_patterns("target","__pycache__",".DS_Store"))
        shutil.copy2(args.spec,stage/"protocol-spec.json"); shutil.copy2(args.vectors,stage/"samples-and-expected.json"); shutil.copy2(args.verification,stage/"verification.json")
        report=load_json(Path(args.verification)); (stage/"verification-report-zh.md").write_text(f"# 中文验证报告\n\n- 语言：{report['language']}\n- 总数：{report['summary']['total']}\n- 已匹配：{report['summary']['passed']}\n- 失败：{report['summary']['failed']}\n- 平台真实导入：未实测\n",encoding="utf-8")
        zip_tree(stage,Path(args.output).resolve())
    finally: shutil.rmtree(stage,ignore_errors=True)
    print(json.dumps({"status":"delivered","output":str(Path(args.output).resolve())},ensure_ascii=False))


def command_package(args: argparse.Namespace) -> None:
    output=Path(args.output).resolve(); zip_tree(ROOT,output)
    with zipfile.ZipFile(output) as archive:
        names=archive.namelist(); required={"SKILL.md","scripts/device_protocol.py","references/protocol-spec.schema.json","templates/java-parser.tpl","templates/python-parser.tpl"}
        missing=required-set(names)
        if missing: raise UserError(f"发行包缺少资源: {sorted(missing)}")
        if any(name.startswith("device-protocol-parser-generator/") or "__pycache__" in name or name.startswith(".") for name in names): raise UserError("发行包出现外壳目录或隐藏缓存")
    print(json.dumps({"status":"packaged","output":str(output),"members":len(names)},ensure_ascii=False))


def parser() -> argparse.ArgumentParser:
    main=argparse.ArgumentParser(description=__doc__); sub=main.add_subparsers(dest="command",required=True)
    validate=sub.add_parser("validate"); validate.add_argument("--spec",required=True)
    extract=sub.add_parser("extract"); extract.add_argument("--input",required=True); extract.add_argument("--output",required=True)
    generate=sub.add_parser("generate"); generate.add_argument("--spec",required=True); generate.add_argument("--language",choices=["java","python"],required=True); generate.add_argument("--output",required=True); generate.add_argument("--package",default="com.safe.link.protocol")
    replay=sub.add_parser("replay"); replay.add_argument("--project",required=True); replay.add_argument("--language",choices=["java","python"],required=True); replay.add_argument("--vectors",required=True); replay.add_argument("--report",required=True)
    deliver=sub.add_parser("deliver"); deliver.add_argument("--project",required=True); deliver.add_argument("--spec",required=True); deliver.add_argument("--vectors",required=True); deliver.add_argument("--verification",required=True); deliver.add_argument("--output",required=True)
    package=sub.add_parser("package"); package.add_argument("--platform",choices=["codex","workbuddy"],required=True); package.add_argument("--output",required=True)
    return main


def main() -> int:
    args=parser().parse_args()
    try:
        if args.command=="validate":
            errors,warnings=validate_spec(load_json(Path(args.spec))); print(json.dumps({"valid":not errors,"errors":errors,"warnings":warnings},ensure_ascii=False,indent=2)); return 1 if errors else 0
        if args.command=="extract": dump_json(Path(args.output),extract_text(Path(args.input))); print(json.dumps({"status":"extracted","output":args.output},ensure_ascii=False)); return 0
        if args.command=="generate": command_generate(args)
        elif args.command=="replay": command_replay(args)
        elif args.command=="deliver": command_deliver(args)
        elif args.command=="package": command_package(args)
        return 0
    except (UserError, OSError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error":type(exc).__name__,"message":str(exc)},ensure_ascii=False),file=sys.stderr); return 2


if __name__=="__main__": raise SystemExit(main())
