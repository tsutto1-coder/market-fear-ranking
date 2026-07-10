# セットアップ手順（所要時間: 約20分）

## 全体の流れ

1. GitHub にリポジトリを作る
2. Google Drive の保存先フォルダを用意する
3. Google サービスアカウントを作る（Googleがフォルダにアクセスする許可）
4. GitHub Secrets に3つのキーを登録する
5. 初回テスト実行する

---

## STEP1: GitHub リポジトリを作る

1. https://github.com にログイン
2. 右上「＋」→「New repository」
3. 名前: `market-fear-ranking`（任意）、Private でOK
4. 「Create repository」をクリック

5. このフォルダのファイルをすべてアップロードする
   - `generate_image.py`
   - `requirements.txt`
   - `.github/workflows/daily.yml`

   （GitHubのWeb画面でドラッグ＆ドロップでアップロード可能）

---

## STEP2: Google Drive の保存先フォルダを用意する

1. Google ドライブ（drive.google.com）を開く
2. 「新規」→「フォルダ」→ 名前: `市場恐怖度ランキング`
3. 作ったフォルダを開く
4. ブラウザのURLを見る:
   `https://drive.google.com/drive/folders/【ここがフォルダID】`
5. このフォルダIDをメモしておく（後でSecretに登録する）

---

## STEP3: Google サービスアカウントを作る

サービスアカウント = GitHub Actions が Google Drive に自動でファイルを置くための「ロボットアカウント」

### 3-1. Google Cloud Console を開く
https://console.cloud.google.com

### 3-2. プロジェクトを作る
- 上部「プロジェクトを選択」→「新しいプロジェクト」
- 名前: `market-fear`（任意）→「作成」

### 3-3. Google Drive API を有効にする
- 左メニュー「APIとサービス」→「ライブラリ」
- 「Google Drive API」を検索→「有効にする」

### 3-4. サービスアカウントを作る
- 左メニュー「APIとサービス」→「認証情報」
- 「認証情報を作成」→「サービスアカウント」
- 名前: `market-fear-bot`（任意）→「完了」

### 3-5. JSON キーをダウンロードする
- 作ったサービスアカウントをクリック
- 「キー」タブ→「鍵を追加」→「新しい鍵を作成」→「JSON」
- ダウンロードされた JSON ファイルを開き、内容をすべてコピー
  （テキストエディタで開いてCtrl+Aで全選択→コピー）

### 3-6. サービスアカウントにフォルダを共有する
- Google ドライブで STEP2 で作ったフォルダを右クリック→「共有」
- ダウンロードしたJSONファイルの中の `"client_email"` の値をコピー
  例: `market-fear-bot@market-fear.iam.gserviceaccount.com`
- そのメールアドレスを入力→「編集者」権限→「送信」

---

## STEP4: GitHub Secrets に登録する

GitHubのリポジトリページ →「Settings」→「Secrets and variables」→「Actions」→「New repository secret」

| Secret名 | 値 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude APIキー（`sk-ant-...`） |
| `GOOGLE_SA_JSON` | STEP3でダウンロードしたJSONファイルの中身を丸ごとペースト |
| `DRIVE_FOLDER_ID` | STEP2でメモしたフォルダID |

---

## STEP5: 初回テスト実行

1. GitHubのリポジトリ →「Actions」タブ
2. 左側「市場恐怖度ランキング 毎日生成」をクリック
3. 右側「Run workflow」→「Run workflow」
4. 数分後、緑のチェックマークが付けば成功
5. Google ドライブの保存先フォルダを開くと `ranking_YYYY-MM-DD.jpg` が入っている

---

## 以降の運用

- 毎日平日18:00に自動実行される
- Google ドライブにその日の画像が追加される
- スマホのGoogle ドライブアプリで確認→ダウンロードしてInstagramに手動投稿

## 実行タイミングを変えたい場合

`daily.yml` の cron を変更する:
```yaml
- cron: '0 9 * * 1-5'   # JST 18:00 平日のみ（現在）
- cron: '0 1 * * 1-5'   # JST 10:00 平日のみ
- cron: '0 9 * * *'     # JST 18:00 毎日（土日含む）
```

UTC → JST は +9時間（例: UTCの0時 = JSTの9時）
