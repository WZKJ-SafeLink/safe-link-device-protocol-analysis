#!/usr/bin/env python3
import argparse, json, sys
from protocol_parser import parse, map_result
def main():
    p=argparse.ArgumentParser(); g=p.add_mutually_exclusive_group(required=True); g.add_argument("--hex"); g.add_argument("--json"); g.add_argument("--modbus"); p.add_argument("--mapped",action="store_true"); a=p.parse_args()
    payload=a.hex if a.hex is not None else json.loads(a.json if a.json is not None else a.modbus)
    result=parse(payload, {}); output=map_result(result,{}) if a.mapped else result
    print(json.dumps(output,ensure_ascii=False,separators=(",",":"),allow_nan=False)); return 0 if result["parseStatus"]!="failed" else 2
if __name__ == "__main__": raise SystemExit(main())
