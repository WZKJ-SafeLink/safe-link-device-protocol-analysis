# 设备协议解析器生成 Skill

本目录是可直接打包的 Skill 源。统一入口为 `scripts/device_protocol.py`，支持资料转写、规则检查、Java/Python 工程生成、回放验证、单次交付和平台打包。

## 最短命令

```bash
cd device-protocol-parser-generator
python3 scripts/device_protocol.py validate --spec examples/demo-binary-spec.json
python3 scripts/device_protocol.py generate --spec examples/demo-binary-spec.json --language python --output ../build/demo-python
python3 ../build/demo-python/parser_cli.py --hex '01 02 58 5F'
```

Java 17：

```bash
python3 scripts/device_protocol.py generate --spec examples/demo-binary-spec.json --language java --output ../build/demo-java
cd ../build/demo-java
mvn -q test
printf '01 02 58 5F\n' | java -cp target/classes com.safe.link.protocol.ParserCli --hex
```

完整研发验收与发行：

```bash
python3 scripts/release_check.py
```

依赖固定为 Python 3.11+ 标准库、Java 17+、Maven 3.9+。生成的 Python 解析器运行时只使用标准库，构建使用 setuptools `>=65.5.0,<66` 与 wheel `0.41.2`；生成的 Java 解析器运行时只使用 JDK。Maven 测试使用 JUnit Jupiter `5.10.2`。PDF 文本提取可选依赖系统 `pdftotext`；不可用时返回明确诊断。

## 最小规则实例

```json
{
  "specVersion": "1.0",
  "protocolId": "demo-level",
  "protocolVersion": "D1",
  "models": ["DEMO-1"],
  "inputEncoding": "hex",
  "maxPayloadBytes": 256,
  "documents": [{"id":"doc-1","file":"demo.md","sourceType":"document"}],
  "messages": [{
    "id": "telemetry", "inputType": "binary",
    "match": {"offset":0,"bytes":"01"}, "length": {"exact":4},
    "fields": [{
      "code":"level","source":{"documentId":"doc-1","location":"table 1 row 2"},
      "selector":{"offset":1,"length":2},"type":"uint16","bitWidth":16,
      "signed":false,"byteOrder":"big","wordOrder":"none","scale":"0.01",
      "offset":"0","unit":"m","unitStatus":"known","required":true,"confirmed":true
    }]
  }],
  "mappings": []
}
```

完整字段、证据、消息和映射约束以 `references/protocol-spec.schema.json` 为准。
