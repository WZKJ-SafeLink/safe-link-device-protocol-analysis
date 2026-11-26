# 规则建模指南

先逐项保存证据，再合并规则。PDF 用“文件 + 页码”，DOCX 用“文件 + 段落/表号/行”，XLSX/CSV 用“文件 + 工作表 + 单元格”，粘贴文本用“行号”。合并单元格、负号、小数点、单位、脚注和版本限定都属于证据。

`confirmed` 只表达规则是否获得文档或厂家确认。`scale: "1"` 表示确认的恒等换算，`scale: null` 表示倍率未知；`unitStatus` 取 `known`、`unknown` 或 `dimensionless`。冲突写入 `conflicts`，保留各解释、来源和影响字段，不覆盖原文。

二进制选择器使用字节 `offset`/`length`；位字段增加 `bitOffset`/`bitLength` 并将共享同一存储字节的字段设 `sharedBits: true`。JSON 使用 `selector.path`（如 `id`、`properties`）或 `selector.collectionPath` + `matchKey` + `matchValue` + `valueKey`。Modbus 使用 `selector.address` 和 `registerCount`，地址一律是实际零基地址，`displayAddress` 只用于证据展示。

独立预期必须先于运行解析器封存，并标明 `expectedSource`：`fictional-golden`、`document-derived`、`vendor-sample` 或 `confirmed-field`。无独立预期只做执行观察，匹配状态为 `not_applicable`。
