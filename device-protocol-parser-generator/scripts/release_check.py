#!/usr/bin/env python3
"""Run isolated cross-language acceptance and build both platform packages."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
TOOL = ROOT / "scripts/device_protocol.py"
SPEC = ROOT / "examples/demo-binary-spec.json"
VECTORS = ROOT / "examples/demo-vectors.json"


def run(command: list[str], cwd: Path = ROOT, timeout: int = 240) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise RuntimeError(f"命令失败 {command}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")


def main() -> int:
    dist = REPO / "dist"; dist.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="protocol-release-") as directory:
        work = Path(directory); py = work / "python"; java = work / "java"
        run([sys.executable, str(TOOL), "validate", "--spec", str(SPEC)])
        run([sys.executable, str(TOOL), "extract", "--input", str(ROOT / "examples/demo-binary-table.csv"), "--output", str(work / "binary-evidence.json")])
        run([sys.executable, str(TOOL), "extract", "--input", str(ROOT / "examples/demo-json-protocol.json"), "--output", str(work / "json-evidence.json")])
        run([sys.executable, str(TOOL), "extract", "--input", str(ROOT / "examples/demo-modbus-table.csv"), "--output", str(work / "modbus-evidence.json")])
        run([sys.executable, str(TOOL), "generate", "--spec", str(SPEC), "--language", "python", "--output", str(py)])
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], py)
        venv = work / "venv"; run([sys.executable, "-m", "venv", str(venv)])
        venv_python = venv / "bin/python"
        run([str(venv_python), "-m", "pip", "install", "--no-deps", "."], py)
        run([str(venv_python), "-c", "from protocol_parser import parse; assert parse('01 02 58 5F')['parseStatus']=='success'"], work)
        run([sys.executable, str(TOOL), "replay", "--project", str(py), "--language", "python", "--vectors", str(VECTORS), "--report", str(work / "python-verification.json")])
        run([sys.executable, str(TOOL), "generate", "--spec", str(SPEC), "--language", "java", "--output", str(java)])
        run(["mvn", "-q", "test"], java)
        run([sys.executable, str(TOOL), "replay", "--project", str(java), "--language", "java", "--vectors", str(VECTORS), "--report", str(work / "java-verification.json")])
        run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], ROOT)
        for platform in ("codex", "workbuddy"):
            package = dist / f"device-protocol-parser-generator-{platform}.zip"
            run([sys.executable, str(TOOL), "package", "--platform", platform, "--output", str(package)])
            with zipfile.ZipFile(package) as archive:
                archive.extractall(work / platform)
            run([sys.executable, str(work / platform / "scripts/device_protocol.py"), "validate", "--spec", str(work / platform / "examples/demo-binary-spec.json")], work / platform)
        python_report = json.loads((work / "python-verification.json").read_text())
        java_report = json.loads((work / "java-verification.json").read_text())
        report = {
            "status": "passed", "documentExtraction": {"binaryTable": "passed", "jsonProtocol": "passed", "modbusTable": "passed"},
            "python": python_report["summary"], "java": java_report["summary"],
            "platformPackages": {"codexOfflineSmoke": "passed", "workbuddyOfflineSmoke": "passed", "codexImport": "not_run", "workbuddyImport": "not_run"},
            "environment": {"python": sys.version.split()[0], "javaTarget": "17", "dependenciesReadyOffline": "Maven plugins/JUnit must be cached"}
        }
        (dist / "release-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        shutil.copy2(work / "python-verification.json", dist / "python-verification.json")
        shutil.copy2(work / "java-verification.json", dist / "java-verification.json")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__": raise SystemExit(main())
