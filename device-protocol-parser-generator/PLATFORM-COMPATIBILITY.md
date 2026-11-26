# 平台兼容状态

| 能力 | Codex | WorkBuddy |
|---|---|---|
| ZIP 结构与离线资源解析 | 实测通过（本地解压 smoke test） | 实测通过（本地解压 smoke test） |
| Skill 实际导入 | 未实测 | 未实测 |
| 宿主附件读取 | 未实测 | 未实测 |
| 宿主命令执行 | 本地 Codex 开发环境实测通过 | 未实测 |
| 客户 ZIP 导出/下载 | 本地生成实测通过 | 未实测 |

验收环境：macOS 26.4 arm64，Python 3.11.5，OpenJDK 25.0.1（按 `--release 17` 编译），Maven 3.9.11。平台客户端版本未由宿主提供，因此不得标记平台导入通过。

离线边界：生成后的 Java/Python 解析器断网运行；Python 仅需标准库，Java 仅需 JRE 17+。首次 Maven 测试需要预先缓存构建插件与 JUnit 5.10.2。宿主生成阶段需要 Python 3.11+；PDF 本地转写另需 `pdftotext`，否则使用宿主附件读取或 OCR 文本。
