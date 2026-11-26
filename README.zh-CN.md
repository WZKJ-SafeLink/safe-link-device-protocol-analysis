# 设备协议解析器生成器

[English](README.md) · [日本語](README.ja.md) · **简体中文**

根据厂家协议或寄存器点表，生成可以独立运行的 Java 17 或 Python 3.11 设备上行解析器。宿主中的智能体负责阅读资料，将解析规则和出处写入 `protocol-spec.json`。本地生成器据此产出源码、可导入的解析入口、命令行工具和测试。构建完成后，解析每条报文都可以离线进行，无需模型或 API Key。

**发行状态**　当前版本使用虚构设备进行研发验证。代码审查发现部分输入会得到错误数值或错误的验证结论。使用客户数据前请先阅读[已知限制](#已知限制)。

## 选择使用方式

| 你的目标 | 使用入口 |
| --- | --- |
| 把协议资料交给智能体 | 使用 [Codex 技能包](dist/device-protocol-parser-generator-codex.zip) 或 [WorkBuddy 技能包](dist/device-protocol-parser-generator-workbuddy.zip)。压缩包根目录包含 [SKILL.md](device-protocol-parser-generator/SKILL.md)。两个平台上的实际导入和附件读取仍待验证。 |
| 直接体验生成结果 | 解压 [Python 客户工程示例](dist/demo-level-python-customer-v1.0.zip)，进入其中的 `project/`，运行 `python3 -m protocol_parser --hex '01 02 58 5F'`。 |
| 在本地生成源码 | 按下方快速入门，从[虚构协议规则](device-protocol-parser-generator/examples/demo-binary-spec.json)生成 Python 或 Java 工程。 |

加载技能并附上寄存器表后，可以这样发起任务：

> 使用 $device-protocol-parser-generator，根据附件中的 Modbus 点表生成 Python 解析器。请标出每个字段对应的单元格，并用厂家提供的样例读数核对结果。

## 快速入门

生成器需要 Python 3.11 或更高版本。运行 Java 示例还需要支持 Java 17 编译目标的 JDK 和 Maven 3.9 或更高版本。生成的解析器只依赖对应语言的运行时。首次构建 Java 工程时可能需要联网获取 Maven 插件和 JUnit，安装 Python 包时可能需要获取 setuptools 和 wheel。

从仓库根目录开始，在同一个 POSIX 兼容终端里执行下列命令。每次初始化都会创建新的输出目录。

```sh
cd device-protocol-parser-generator
work=$(mktemp -d)
tool=scripts/device_protocol.py
spec=examples/demo-binary-spec.json
vectors=examples/demo-vectors.json
python3 "$tool" validate --spec "$spec"
```

生成 Python 工程并直接从源码运行：

```sh
python3 "$tool" generate --spec "$spec" --language python --output "$work/python"
(cd "$work/python" && python3 -m protocol_parser --hex '01 02 58 5F')
```

使用 Java 时，先构建并测试，再把同一条 HEX 报文送入标准输入：

```sh
python3 "$tool" generate --spec "$spec" --language java --output "$work/java"
(cd "$work/java" && mvn -q test)
printf '%s\n' '01 02 58 5F' | java -cp "$work/java/target/classes" com.safe.link.protocol.ParserCli --hex
```

两种语言解析 D1 示例帧时都应返回 `parseStatus: success`。字节 `02 58` 表示液位原值 600，乘以倍率后得到 6 m。末字节 `5F` 表示电量 95%。在业务代码中可以调用 Python 的 `protocol_parser.parse(payload, context)`，或 Java 的 `com.safe.link.protocol.DeviceParser.parse(payload, context)`。

### JSON 载荷与寄存器块

以下示例分别处理已收到的 MQTT JSON 载荷和已采集的保持寄存器块。设备连接、消息接收和分帧由调用方负责。可以用上一步生成的 Python 工程运行：

```sh
python3 "$work/python/parser_cli.py" --json '{"id":"00123","properties":[{"name":"batt","value":95},{"name":"level","value":600}]}' --mapped
python3 "$work/python/parser_cli.py" --modbus '{"registerType":"holding","startAddress":0,"registers":[1,2,16320,0]}'
```

映射后的 JSON 会保留设备号 `"00123"` 的前导零，并将 `6` 写入 `data.levelM`。寄存器示例中，前两个寄存器解出计数器值 `65538`，后两个解出压力 `1.5 bar`。

## 接入自己的协议

1. 收集协议版本、设备型号、输入形式、目标语言及样例读数。提供二进制样例时，请明确标注 HEX。
2. 从 TXT、Markdown、JSON、CSV、DOCX、XLSX 或文本型 PDF 提取带位置的记录。PDF 提取使用本机的 `pdftotext`。扫描件可提供带页码的人工转录或 OCR 文字。

```sh
python3 "$tool" extract --input examples/demo-modbus-table.csv --output "$work/evidence.json"
```

3. 阅读提取结果，将字段位置、类型、字节序和字序、倍率、单位及出处写入规则。确认恒等换算时用 `"1"`，倍率未知时用 `null`。在生成代码前单独保存厂家预期值，供后续核对。详见[规则编写指南](device-protocol-parser-generator/references/authoring.md)和[规则 Schema](device-protocol-parser-generator/references/protocol-spec.schema.json)。
4. 将 `spec` 和 `vectors` 指向自己的文件，校验规则，再生成到新目录。客户自定义 JSON 的映射写在规则的 `mappings` 数组内。接入 Safe Link 时需要客户实际使用的输出契约及其版本。

## 验证与交付

默认结果包含协议标识及版本、消息类型、属性、警告和错误。每个属性记录字段编码、原值、工程值和单位。`success` 表示解析成功，`partial` 表示存在字段级诊断，`failed` 表示解析失败且属性为空。示例 CLI 在成功或部分成功时返回退出码 0，业务解析失败时返回 2。详见[结果 Schema](device-protocol-parser-generator/references/result.schema.json)和[诊断码](device-protocol-parser-generator/references/error-codes.md)。

以下命令用刚生成的 Python 工程回放样例并生成客户 ZIP。包内含源码工程、字段出处、样例与预期、验证结果 JSON 和中文摘要。分享前可用最后一条命令核对成员清单。

```sh
python3 "$tool" replay --project "$work/python" --language python --vectors "$vectors" --report "$work/verification.json"
python3 "$tool" deliver --project "$work/python" --spec "$spec" --vectors "$vectors" --verification "$work/verification.json" --output "$work/customer.zip"
unzip -l "$work/customer.zip"
```

回放 Java 工程时，使用 `--project "$work/java" --language java`。维护仓库时可执行以下命令运行单元测试，并在 `dist/` 下重建两个平台包和验证 JSON。发行脚本会创建新的 Python 环境并调用 Maven。

```sh
python3 -m unittest discover -s tests
python3 scripts/release_check.py
```

## 已知限制

- **交付文件范围。** 交付命令会递归复制工程目录。请使用专门的生成目录，并检查 ZIP 中是否混入无关资料、凭据或外部符号链接指向的文件。
- **报文结构。** 两个后端都可能接受带多余尾字节的定长帧，忽略必需上下文，并在消息判别条件重叠时采用第一条规则。越界的校验字节位置可能通过规则检查，随后导致 CLI 异常退出。
- **寄存器和映射。** Java 可能误读有符号小端寄存器。两个后端都可能忽略目标类型或转换要求，仍返回映射成功。交付前需对照厂家读数和客户输出契约核对。
- **验证覆盖。** 已发布报告记录的是每种语言各 5 条虚构向量匹配。回放工具可能将 JSON 的 `true` 和 `1` 判为相等，部分诊断细节也未参与比对。REG-02 的封存预期是寄存器缺失，没有断言浮点数的正确值。当前规则 Schema 也会拒绝包含必填字段 `affected` 的冲突记录。

[验证记录](dist/release-verification.json) · [平台兼容状态](device-protocol-parser-generator/PLATFORM-COMPATIBILITY.md) · [样例输入与预期](device-protocol-parser-generator/examples/demo-vectors.json)
