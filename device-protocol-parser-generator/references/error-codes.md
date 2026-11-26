# 稳定错误码

| 代码 | 含义 | 状态 |
|---|---|---|
| `INVALID_HEX` | 非 HEX 字符或奇数位 | failed |
| `PAYLOAD_TOO_LARGE` | 超过规则上限 | failed |
| `UNKNOWN_MESSAGE` | 无消息判别条件匹配 | failed |
| `FRAME_TRUNCATED` | 定长帧或字段截断 | failed |
| `CHECKSUM_MISMATCH` | 强制校验失败 | failed |
| `CHECKSUM_UNSUPPORTED` | 规则要求未实现算法 | failed |
| `FIELD_SCALE_UNKNOWN` | 倍率未知，保留原值 | partial |
| `FIELD_UNIT_UNKNOWN` | 单位未知 | partial |
| `FIELD_SENTINEL` | 原始值为哨兵 | partial |
| `FIELD_TYPE_MISMATCH` | JSON/字段类型不匹配 | partial/failed |
| `FIELD_MISSING` | 必填字段缺失 | partial/failed |
| `DUPLICATE_JSON_FIELD` | 数组标识重复 | partial |
| `REGISTER_VALUE_INVALID` | 寄存器不在 0..65535 | failed |
| `REGISTER_MISSING` | 跨寄存器字段缺少地址 | partial/failed |
| `NON_FINITE_NUMBER` | float32 为 NaN/Infinity | partial |
| `MAPPING_REQUIRED_MISSING` | 目标映射必填来源缺失 | failed |
