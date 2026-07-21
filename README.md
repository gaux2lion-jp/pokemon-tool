# ポケモンカード買取価格比較ツール

ワンピースカード用ツール（`kaitori-tool`）の姉妹版です。同じ仕組み（サイトごとの
価格取得 → 前回比較 → Discord通知 → GitHub Actionsでの自動実行）を、
ポケモンカードのBOX向けに作っています。商品数が多いため、Discordには
「変更点の要約」だけを送り、詳細な全商品一覧は**クリックで見られるWebページ**
（GitHub Pages）に置く構成になっています。

## 対応サイト（9サイト）

- 買取BASE／買取ホムラ／Runto買取／買取ルデヤ／買取エノキング
- モバイル一番／買取商店／買取1丁目／トレカラウンジ

※買取ソムリエは構造を実機確認できなかったため未実装です（`--debug`で得られる
HTMLを共有いただければ対応します）。

## 対象商品

`config.json` に約106商品を登録済みです（現行シリーズ〜歴代シリーズ、
地域限定スペシャルBOXまで）。

## セットアップ

```
pip install -r requirements.txt
python pokemon_scraper.py
```

## GitHub Actionsでの自動実行・Discord通知の設定

ワンピース版とほぼ同じ手順です。

1. GitHubに**非公開リポジトリ**を作り、このフォルダの中身を丸ごとアップロード
2. Settings → Secrets and variables → Actions で `DISCORD_WEBHOOK_URL` を登録
3. cron-job.orgなど外部サービスから、GitHubの
   `https://api.github.com/repos/ユーザー名/リポジトリ名/actions/workflows/pokemon_check.yml/dispatches`
   に対して1時間ごとにPOSTリクエストを送るよう設定（ワンピース版と同じ手順）

## GitHub Pages（クリックで見る一覧ページ）の設定 ※ポケモン版で新規追加

1. リポジトリの **Settings → Pages** を開く
2. 「Build and deployment」の「Source」で **Deploy from a branch** を選択
3. Branch を **main**、フォルダを **/docs** に設定して保存
4. 数分待つと、`https://ユーザー名.github.io/リポジトリ名/` でページが公開されます
5. `config.json` の `report_url` に、そのURLを貼り付けてください

```json
"report_url": "https://ユーザー名.github.io/リポジトリ名/"
```

これで、Discordの通知に「詳細はこちら」というリンクが付き、タップすると
全商品・全サイトの価格一覧がスマホやPCのブラウザで見られるようになります。

## うまく価格が取れないとき

`python pokemon_scraper.py --debug` を実行すると、`debug_html/` フォルダに
実際に取得した生のHTMLが保存されます。特に買取ソムリエは未検証なので、
エラーや0件になった場合はこのファイルを共有してください。
