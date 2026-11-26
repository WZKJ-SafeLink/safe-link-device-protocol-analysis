# デバイスプロトコル・パーサー生成ツール

[English](README.md) · **日本語** · [简体中文](README.zh-CN.md)

機器の上り通信を解析する Java 17 または Python 3.11 のソースコードを生成します。ホスト側のアシスタントがメーカーの仕様書やレジスタ表を読み、解析ルールとその出典を `protocol-spec.json` に記録します。ローカルの生成ツールはこの仕様を基に、呼び出し用 API、CLI、テストを備えたプロジェクトを生成します。ビルド後のパーサーはオフラインで動作し、AI モデルや API キーは不要です。

**リリース状況**　架空の機器による評価段階です。実際のレビューで、値が誤っていても解析や検証が成功扱いになる条件が見つかっています。顧客データを扱う前に[既知の制約](#既知の制約)を確認してください。

## 利用方法を選ぶ

| 目的 | 使用するファイル |
| --- | --- |
| アシスタントに仕様書を渡す | [Codex 用 ZIP](dist/device-protocol-parser-generator-codex.zip) または [WorkBuddy 用 ZIP](dist/device-protocol-parser-generator-workbuddy.zip)。アーカイブの直下に [SKILL.md](device-protocol-parser-generator/SKILL.md) があります。両ホストへの実際のインポートと添付ファイルの読み取りは未検証です。 |
| 生成済みのパーサーを試す | [Python のサンプル納品物](dist/demo-level-python-customer-v1.0.zip)を展開し、`project/` で `python3 -m protocol_parser --hex '01 02 58 5F'` を実行します。 |
| 手元でコードを生成する | 次の手順で[架空の機器仕様](device-protocol-parser-generator/examples/demo-binary-spec.json)から Python または Java のプロジェクトを生成します。 |

スキルを読み込み、レジスタ表を添付した後の依頼例です。

> $device-protocol-parser-generator を使い、添付の Modbus レジスタ表から Python パーサーを生成してください。各フィールドの出典セルを示し、メーカーのサンプル測定値と照合してください。

## クイックスタート

生成には Python 3.11 以降が必要です。Java の例では Java 17 向けにコンパイルできる JDK と Maven 3.9 以降も使用します。生成したパーサーの実行に必要なのは各言語のランタイムのみです。初回の Java ビルドでは Maven プラグインと JUnit、Python パッケージのインストールでは setuptools と wheel の取得にネットワーク接続が必要な場合があります。

リポジトリのルートから、以下のコマンドを同じ POSIX 互換シェルで実行します。実行のたびに新しい出力先が作られます。

```sh
cd device-protocol-parser-generator
work=$(mktemp -d)
tool=scripts/device_protocol.py
spec=examples/demo-binary-spec.json
vectors=examples/demo-vectors.json
python3 "$tool" validate --spec "$spec"
```

Python 版を生成し、ソースから直接実行します。

```sh
python3 "$tool" generate --spec "$spec" --language python --output "$work/python"
(cd "$work/python" && python3 -m protocol_parser --hex '01 02 58 5F')
```

Java 版を使う場合は Maven のテストを実行してから、同じ HEX フレームを標準入力に渡します。

```sh
python3 "$tool" generate --spec "$spec" --language java --output "$work/java"
(cd "$work/java" && mvn -q test)
printf '%s\n' '01 02 58 5F' | java -cp "$work/java/target/classes" com.safe.link.protocol.ParserCli --hex
```

D1 フレームの期待値は両言語とも `parseStatus: success` です。`02 58` は液位の生値 600 で、換算後は 6 m です。`5F` は電池残量 95% を表します。ライブラリからは Python の `protocol_parser.parse(payload, context)`、Java の `com.safe.link.protocol.DeviceParser.parse(payload, context)` を呼び出せます。

### JSON ペイロードとレジスタブロック

対象は受信済みの MQTT JSON ペイロードと、読み取り済みの保持レジスタです。通信、フレームの切り出し、機器へのアクセスは呼び出し側で行います。先ほど生成した Python 版で次の例を試せます。

```sh
python3 "$work/python/parser_cli.py" --json '{"id":"00123","properties":[{"name":"batt","value":95},{"name":"level","value":600}]}' --mapped
python3 "$work/python/parser_cli.py" --modbus '{"registerType":"holding","startAddress":0,"registers":[1,2,16320,0]}'
```

JSON のマッピングでは機器 ID の `"00123"` を保持し、`data.levelM` に `6` を出力します。レジスタの例では、先頭の 2 ワードがカウンター値 `65538`、続く 2 ワードが圧力 `1.5 bar` になります。

## 新しいプロトコルを追加する

1. プロトコルの版、機種、入力形式、出力言語、サンプル測定値を用意します。バイナリの例には HEX であることを明記します。
2. TXT、Markdown、JSON、CSV、DOCX、XLSX、テキスト PDF から位置情報付きで内容を抽出します。PDF にはローカルの `pdftotext` が必要です。スキャン文書にはページ番号を付けた書き起こしか OCR テキストを用意します。

```sh
python3 "$tool" extract --input examples/demo-modbus-table.csv --output "$work/evidence.json"
```

3. 抽出結果を読み、各フィールドの位置、型、バイト順・ワード順、倍率、単位、出典を仕様に記録します。倍率 1 が確認済みなら `"1"`、不明なら `null` とします。照合用の期待値はコード生成前に別途保存します。[記述ガイド](device-protocol-parser-generator/references/authoring.md)と[仕様スキーマ](device-protocol-parser-generator/references/protocol-spec.schema.json)を参照してください。
4. `spec` と `vectors` を自分のファイルに切り替え、仕様を検証してから新しいディレクトリに生成します。顧客向け JSON の変換規則は仕様の `mappings` 配列に記述します。Safe Link との連携には顧客が使用する出力仕様とその版が必要です。

## 検証と納品

標準出力の JSON にはプロトコル ID と版、メッセージ種別、属性、警告、エラーが含まれます。各属性にはコード、生値、換算値、単位があります。`success` は解析成功、`partial` はフィールド単位の診断あり、`failed` は属性が空の解析失敗を表します。サンプル CLI の終了コードは成功・部分成功時に 0、解析失敗時に 2 です。[結果スキーマ](device-protocol-parser-generator/references/result.schema.json)・[診断コード](device-protocol-parser-generator/references/error-codes.md)

次の例では、生成した Python プロジェクトでテストデータを再生し、納品用 ZIP を作ります。ZIP にはソース、フィールドの出典、入力と期待値、検証結果の JSON、中国語の検証概要が入ります。共有前にファイル一覧を確認してください。

```sh
python3 "$tool" replay --project "$work/python" --language python --vectors "$vectors" --report "$work/verification.json"
python3 "$tool" deliver --project "$work/python" --spec "$spec" --vectors "$vectors" --verification "$work/verification.json" --output "$work/customer.zip"
unzip -l "$work/customer.zip"
```

Java の再生には `--project "$work/java" --language java` を指定します。リポジトリの保守時には次のコマンドで単体テストを実行し、`dist/` の配布用 ZIP と検証結果 JSON を再生成します。リリーススクリプトは新しい Python 環境を作成し、Maven も実行します。

```sh
python3 -m unittest discover -s tests
python3 scripts/release_check.py
```

## 既知の制約

- **納品対象のファイル**　納品時にはプロジェクトを再帰的にコピーします。生成専用ディレクトリを使用し、ZIP に無関係なファイル、秘密情報、ディレクトリ外のファイルを指すリンク先の内容が含まれていないか確認してください。
- **フレームの判定**　両言語とも定長フレームの余分な末尾バイトを受け入れます。必須のコンテキストも検査されず、識別条件が重なると先に定義したメッセージが選ばれることがあります。チェックサム位置の範囲外指定が検証を通り、実行時に CLI が異常終了する場合もあります。
- **レジスタとマッピング**　Java 版は符号付きリトルエンディアンのレジスタを誤読する場合があります。また両言語とも、出力型や変換指定を適用しないままマッピング成功を返す場合があります。メーカーの測定値と顧客の出力スキーマで照合してください。
- **検証範囲**　公開レポートでは架空のテストデータが各言語で 5 件一致しています。再生処理は JSON の `true` と `1` を同じと見なす場合があり、診断の詳細も比較対象から外れます。REG-02 が確認しているのはレジスタ不足のエラーで、浮動小数点値の正常な復号は対象外です。また、現在の仕様スキーマは必須の `affected` を含む競合情報を受理できません。

[検証記録](dist/release-verification.json) · [プラットフォーム互換性](device-protocol-parser-generator/PLATFORM-COMPATIBILITY.md) · [サンプル入力と期待値](device-protocol-parser-generator/examples/demo-vectors.json)
