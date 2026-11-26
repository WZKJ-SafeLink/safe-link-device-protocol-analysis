# Python 设备解析器

要求 Python 3.11+，运行时无第三方依赖；构建固定使用 setuptools 65.5.x 和 wheel 0.41.2。预先缓存构建依赖后可离线安装。

```bash
python3 -m pip install .
python3 -m unittest discover -s tests
python3 parser_cli.py --hex '01 02 58 5F'
python3 -m protocol_parser --json '{"id":"00123","properties":[]}'
```

CLI stdout 仅输出 JSON；解析失败退出码 2，工具参数错误由 argparse 返回 2。公开入口：`protocol_parser.parse(payload, context)`。
