# Device Protocol Parser Generator

**English** · [日本語](README.ja.md) · [简体中文](README.zh-CN.md)

Generate a standalone Java 17 or Python 3.11 parser for device telemetry. The host assistant reads a manufacturer's protocol or register table and records the rules and their sources in `protocol-spec.json`. The local generator turns those rules into a source project with a library entry point, CLI and tests. Once built, the parser runs offline without an AI model or API key.

**Release status:** Evaluation with fictional devices. The review found cases that silently produce incorrect values or false verification results. See [Known limitations](#known-limitations) before using the packages with customer data.

## Choose a starting point

| What you want to do | Where to start |
| --- | --- |
| Give a protocol document to an assistant | [Codex skill ZIP](dist/device-protocol-parser-generator-codex.zip) or [WorkBuddy skill ZIP](dist/device-protocol-parser-generator-workbuddy.zip). The archive root contains [SKILL.md](device-protocol-parser-generator/SKILL.md). Actual host import and attachment handling still need testing. |
| Try a generated parser | Unpack the [Python customer example](dist/demo-level-python-customer-v1.0.zip). From its `project/` directory, run `python3 -m protocol_parser --hex '01 02 58 5F'`. |
| Generate either language locally | Follow the quick start below using the [fictional protocol spec](device-protocol-parser-generator/examples/demo-binary-spec.json). |

Example request after loading the skill and attaching the register table:

> Use $device-protocol-parser-generator to generate a Python parser from the attached Modbus table. Cite the cell for each field and verify the output against the manufacturer's sample readings.

## Quick start

Use Python 3.11+ for the generator. The Java example also requires a JDK with Java 17 support and Maven 3.9+. Both generated parsers use only their language runtime. First-time builds may need network access for Maven plugins and JUnit, or for setuptools and wheel when installing the Python package.

Start at the repository root and keep the same POSIX shell open. The setup creates a fresh output directory for each run.

```sh
cd device-protocol-parser-generator
work=$(mktemp -d)
tool=scripts/device_protocol.py
spec=examples/demo-binary-spec.json
vectors=examples/demo-vectors.json
python3 "$tool" validate --spec "$spec"
```

Generate and run Python directly from source:

```sh
python3 "$tool" generate --spec "$spec" --language python --output "$work/python"
(cd "$work/python" && python3 -m protocol_parser --hex '01 02 58 5F')
```

Or generate Java, run its Maven test and pass the same HEX frame on standard input:

```sh
python3 "$tool" generate --spec "$spec" --language java --output "$work/java"
(cd "$work/java" && mvn -q test)
printf '%s\n' '01 02 58 5F' | java -cp "$work/java/target/classes" com.safe.link.protocol.ParserCli --hex
```

Both commands for the D1 frame should report `parseStatus: success`. Bytes `02 58` give a raw level of 600, scaled to 6 m. Byte `5F` gives a battery level of 95%. The Python library entry point is `protocol_parser.parse(payload, context)`; Java exposes `com.safe.link.protocol.DeviceParser.parse(payload, context)`.

### JSON payloads and register blocks

The examples use an already received MQTT JSON payload and an already collected block of holding registers. The caller handles transport, framing and device access. With the Python project generated above:

```sh
python3 "$work/python/parser_cli.py" --json '{"id":"00123","properties":[{"name":"batt","value":95},{"name":"level","value":600}]}' --mapped
python3 "$work/python/parser_cli.py" --modbus '{"registerType":"holding","startAddress":0,"registers":[1,2,16320,0]}'
```

The mapped JSON keeps device ID `"00123"` and writes `6` to `data.levelM`. In the register example, the first two registers give the counter `65538`; the next two give the pressure `1.5 bar`.

## Model a new protocol

1. Collect the protocol version, device model, input format, desired language and sample readings. Use explicit HEX for binary examples.
2. Extract text with source locations from TXT, Markdown, JSON, CSV, DOCX, XLSX or a text PDF. PDF extraction uses local `pdftotext`. For scanned pages, provide a transcription or OCR text with page references.

```sh
python3 "$tool" extract --input examples/demo-modbus-table.csv --output "$work/evidence.json"
```

3. Read the extracted records and write the spec. Record each selector, type, byte or word order, scale, unit and source location. Use `"1"` for a confirmed identity scale and `null` for an unknown scale. Keep independent expected readings before generating code. See the [authoring guide](device-protocol-parser-generator/references/authoring.md) and [spec schema](device-protocol-parser-generator/references/protocol-spec.schema.json).
4. Set `spec` and `vectors` to your own files, validate, and generate into a new directory. Put customer output rules in the spec's `mappings` array. Safe Link integration requires the customer's actual contract and version.

## Verify and deliver

The default result includes the protocol ID and version, message type, properties, warnings and errors. Each property has a code, raw value, engineering value and unit. `success` indicates a decoded message, `partial` carries field diagnostics and `failed` has empty properties. The demo CLI exits with 0 for success or partial and 2 for a failed parse. See the [result schema](device-protocol-parser-generator/references/result.schema.json) and [diagnostics](device-protocol-parser-generator/references/error-codes.md).

Run these commands against the freshly generated Python project. The ZIP includes the project, field sources, sample inputs and expectations, verification JSON and a Chinese summary. Inspect the archive members before sharing it.

```sh
python3 "$tool" replay --project "$work/python" --language python --vectors "$vectors" --report "$work/verification.json"
python3 "$tool" deliver --project "$work/python" --spec "$spec" --vectors "$vectors" --verification "$work/verification.json" --output "$work/customer.zip"
unzip -l "$work/customer.zip"
```

For Java replay, use `--project "$work/java" --language java`. For repository maintenance, the commands below run the unit tests and rebuild the platform ZIPs and verification JSON in `dist/`. The release script uses a fresh Python environment and runs Maven.

```sh
python3 -m unittest discover -s tests
python3 scripts/release_check.py
```

## Known limitations

- **Delivery contents.** Delivery recursively copies the project. Use a dedicated generated directory and check the archive for unrelated files, secrets and links to external files.
- **Frame validation.** Both backends accept trailing bytes on fixed-length frames, skip required context checks and can select the first of two overlapping message signatures. An out-of-range checksum position can pass validation and then crash the CLI.
- **Register values and mappings.** Java can misread signed, little-endian registers. Both backends can return a successful mapping that ignores the target type or requested conversion. Check these cases against manufacturer readings and the target schema.
- **Verification coverage.** The published report records five matched fictional vectors per language. Replay can equate JSON `true` with `1` and omit diagnostic details. REG-02 expects a missing-register error and does not assert the positive float value. The spec schema also rejects nonempty conflict entries that supply the required `affected` field.

[Recorded verification](dist/release-verification.json) · [Platform compatibility](device-protocol-parser-generator/PLATFORM-COMPATIBILITY.md) · [Sample inputs and expectations](device-protocol-parser-generator/examples/demo-vectors.json)
