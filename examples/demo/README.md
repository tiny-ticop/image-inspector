# 人工サンプル

すべてプログラムで生成した画像・0/1マスクです。実際の機台画像は含みません。2機台×3角度×4画像です。

リポジトリ直下でセットアップした後、以下を実行します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\frame_viewer\start.ps1 --config .\examples\demo\config.json
powershell -NoProfile -ExecutionPolicy Bypass -File .\mask_review_tool\start.ps1 --config .\examples\demo\config.json
```

それぞれ別の端末で起動し、表示されたURLを開いてください。出力はこのフォルダ内の `outputs/` に保存され、Gitには含めません。

再生成は `.\.venv\Scripts\python.exe -m loom_tools.demo`。手元の実データには適用しません。
