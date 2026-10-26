# Loom Image Tools

Windows向けのローカル画像確認・解析ツールです。Python 3.12（64bit）とブラウザを使います。実画像・実マスク・確認結果・解析結果は配布物に含めません。

| ツール | 用途 |
|---|---|
| `frame_viewer` | 機台・角度ごとの画像再生、複数機台の並列表示、変動解析、教師なしパターン発見 |
| `mask_review_tool` | 原画像とマスクの照合、確認状態・メモ、連結した糸領域への種別指定 |

## 初回セットアップ

1. Python 3.12の64bit版をインストールします。`python --version` または `py -3.12 --version` で確認できます。
2. GitHubの「Code → Download ZIP」で取得して展開するか、cloneします。ZIP利用ならGitは不要です。
3. 展開先のPowerShellで実行します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

`.venv` の作成、依存導入、ツールの登録・読み込み確認を行います。初回はインターネット接続が必要です。システム全体のPythonや実行ポリシーは変更しません。失敗時は表示を確認して同じコマンドを再実行できます。

## 人工サンプルで試す

2機台×3角度×4枚の人工画像とマスクを同梱しています。別々の端末で起動します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\frame_viewer\start.ps1 --config .\examples\demo\config.json
```

http://127.0.0.1:8769/ を開きます。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\mask_review_tool\start.ps1 --config .\examples\demo\config.json
```

http://127.0.0.1:8765/ を開きます。終了は各端末でCtrl+C。導入後の利用にインターネット接続は不要です。

## 自分のデータを指定する

`config.example.json` を `config.local.json` にコピーし、入力・出力を変更します。Windowsでも `/` を使うとJSONのパスを簡単に記述できます。

```json
{
  "raw_dir": "D:/datasets/loom/raw",
  "mask_dir": "D:/datasets/loom/masks",
  "frame_viewer": {"output_dir": "D:/results/frame_viewer", "port": 8769},
  "mask_review_tool": {"output_dir": "D:/results/mask_review", "port": 8765}
}
```

起動時に `--config .\config.local.json` を指定します。相対パスは設定ファイルの置かれたフォルダを基準に解決します。CLIの `--raw-dir`、`--mask-dir`、`--output-dir`、`--port` は設定ファイルより優先し、CLI上の相対パスは実行した端末の現在位置を基準にします。

設定を渡さない場合は、リポジトリ内の `data/raw`、`data/masks` と各ツール内の `outputs` を使う従来互換の動作です。入力・出力先は起動時に表示します。原画像やマスク内に出力先を設定することはできません。

入力の構造は次の形式です。機台名・角度・枚数は固定しません。

```text
raw/機台名/delay/角度/任意の名前.jpg
masks/機台名/delay/角度/任意の名前.png
```

原画像は `.jpg` / `.jpeg`、マスクは0/1のグレースケールPNGです。拡張子の大文字・小文字は問いません。対応は同じ相対パス・拡張子を除く名前で照合します。`frame_viewer` はマスクなしで使えます。原画像・元マスクは変更しません。

## 結果の引き継ぎ

- 出力フォルダは入力データごとに分けることをおすすめします。別PCへはデータ・出力・設定を移し、設定のパスを変更します。
- `mask_review_tool` は相対パスと画像・マスクの内容ハッシュで結果を結び付けます。同じデータの移動は可能です。同名でも内容が変わった場合、旧結果は隔離JSONに保持し、新画像には適用しません。
- 従来形式の `reviews.json` は初回起動時にバックアップし、現在のデータへ結び付けます。過去の画像との同一性は検証できないため、画面に移行通知を表示します。元の記録はバックアップに残します。
- 入力を変更した場合はサーバーを再起動します。起動中に画像・マスクが変更された場合、確認結果の保存を拒否します。
- 変動解析のキャッシュは入力ハッシュ・設定・手法バージョンで管理します。自動分類は探索結果であり、正解ラベルではありません。

詳しい操作・解析方法は [frame_viewer](frame_viewer/README.md)、[mask_review_tool](mask_review_tool/README.md) を参照してください。

## 開発・テスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m unittest discover -s frame_viewer/tests -p "test_*.py"
node .\frame_viewer\tests\test_player.cjs
```

テストは人工データを使い、実データを必要としません。ブラウザテストにはNode.js 22以降とChromeまたはEdgeが必要です。CI定義は `docs/ci-workflow.yml` に同梱しています。GitHub上で `.github/workflows/ci.yml` として追加すると有効になります（workflow更新権限が必要です）。通常利用にNode.jsは不要です。

依存を含む環境はPCごとに作成します。`.venv` を他PCへコピーしないでください。必要なら `setup.ps1 --check-only` で導入済み環境を点検できます。実画像・出力・個人用設定はGit管理せず、人工サンプルだけを共有します。
