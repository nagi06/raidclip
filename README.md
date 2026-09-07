# RaidClip

レイドの録画 (mp4) から「ここからここまで」を選んで切り出し、Discord に上げやすいサイズで保存するだけの Windows 用アプリです。

## ダウンロード

**[最新版 RaidClip-windows.zip をダウンロード](https://github.com/nagi06/raidclip/releases/latest/download/RaidClip-windows.zip)**
(すべての版: [Releases](https://github.com/nagi06/raidclip/releases))

zip を展開して `RaidClip.exe` を起動するだけです。インストール不要、ffmpeg 同梱。
初回起動時に Windows の SmartScreen が出た場合は「詳細情報」→「実行」で通ります。

## 使い方

1. `RaidClip-windows.zip` を展開し、`RaidClip.exe` を起動する。
2. mp4 をウィンドウにドラッグ&ドロップ (または「動画を開く」)。
3. 範囲を決める。方法は 3 つあり、どれでも可。
   - バーの下にある **▽ ハンドルをドラッグ** (左が開始、右が終了)。ドラッグ中はその位置の映像が表示される
   - プレビューを再生・シークして **I キー** で開始位置、**O キー** で終了位置
   - 数値欄に `1:23.5` のように直接入力
   「範囲を再生」で確認できる。
4. 保存モードを選ぶ。
   | モード | 速度 | 説明 |
   |---|---|---|
   | 高速 (無劣化) | 数秒 | 再エンコードしない。開始位置がキーフレーム単位 (数秒) で手前にずれることがある |
   | 正確 (再エンコード) | 実時間の 1/3〜1/2 程度 | フレーム単位で正確。画質は CRF 20 で十分きれい |
   | Discord のサイズに収める | 正確モードの約 2 倍 | 10MB / 25MB / 50MB / 500MB を選ぶと、そのサイズに収まるビットレートで二パスエンコードする。足りない場合は自動で 720p / 480p に縮小 |
5. 「切り出して保存…」→ 保存先を指定。終わったら「保存先フォルダを開く」から Discord にドラッグ。

### 静止画に注釈 (カンペ用)

プレビューで狙いの場面まで送り、**S キー** (または「静止画に注釈」) を押すと、そのフレームを元動画から切り出して注釈ウィンドウが開きます。

- 道具: 矢印 (A) / 直線 (L) / 四角 (R) / 円 (E) / ペン (P) / 文字 (T) / 番号 (N) / モザイク (B) / トリミング (C)
- 番号は置いた順に ① ② ③ と自動で増えます。モザイクは名前欄やチャット欄を隠す用途で、範囲をドラッグします。
- 8 色 + 太さ 3 段階。Ctrl+Z / Ctrl+Y で元に戻す・やり直し。
- 出力は「PNG で保存」か「クリップボードにコピー」(Discord に Ctrl+V で貼れます)。
- 解像度は元動画のまま。ただし横 1920 を超える動画は 1920 に縮小します。

### キー操作

| キー | 動作 |
|---|---|
| Space / K | 再生・一時停止 |
| I / O | 開始 / 終了を現在位置にする |
| ← / → | 5 秒戻る / 進む |
| Shift+← / Shift+→ (, / .) | 0.1 秒戻る / 進む |
| S | 現在のフレームを静止画にして注釈 |
| Ctrl+O / Ctrl+S | 開く / 保存 |

### Discord の上限の目安

無料アカウントは 1 ファイル 10MB、Nitro Basic は 50MB、Nitro は 500MB です (2025 年時点)。
10MB だと 1080p で 30 秒程度、720p で 1 分程度が実用的な限界なので、長くなるなら 480p 縮小を受け入れるか Nitro 枠を使ってください。

## ソースから動かす

```
pip install -r requirements.txt
python raidclip.py
```

`ffmpeg.exe` と `ffprobe.exe` を PATH か、リポジトリ直下の `ffmpeg/` フォルダに置いてください
([gyan.dev](https://www.gyan.dev/ffmpeg/builds/) の release-essentials で可)。

## exe を作る

- GitHub Actions: `v0.1.0` のようなタグを push すると、ffmpeg 同梱の zip が Release に付きます。
  Actions タブから手動実行 (Run workflow) する場合は、`release_tag` にタグ名を入れると Release が作られ、空欄なら Artifacts に zip が出るだけです。
- ローカル: `build.bat` を実行すると `dist\RaidClip\RaidClip.exe` ができます。ffmpeg を同梱したい場合は、先にリポジトリ直下の `ffmpeg\` フォルダに `ffmpeg.exe` と `ffprobe.exe` を置いてください。

## テスト

```
pip install -r requirements-dev.txt
python -m pytest -q tests
```

## 構成

- `raidclip/ffmpeg_tools.py` … ffmpeg の探索、動画情報の取得、各モードのコマンド生成 (GUI 非依存)
- `raidclip/app.py` … PySide6 の GUI。プレビュー再生、範囲指定、QProcess で ffmpeg 実行と進捗表示
- `raidclip/annotate.py` … 静止画の注釈ダイアログ (描画・モザイク・トリミング・PNG 保存・クリップボード)
- `RaidClip.spec` / `build.bat` / `.github/workflows/build.yml` … 配布用ビルド

## ライセンス

MIT。同梱の ffmpeg は GPL ビルド (BtbN/FFmpeg-Builds) で、ライセンスは `ffmpeg/LICENSE-ffmpeg.txt` を参照。
