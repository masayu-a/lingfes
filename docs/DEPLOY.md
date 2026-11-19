# 国語研 www2.ninjal.ac.jp/lingfes/ 静的HTML公開手順（承認が必要）

## 要件

- 国語研 `www2` の公開ディレクトリに **HTML/CSSのみ**を配置する。
- JavaScript、サーバーサイドスクリプト、実行環境、JSON読込のためのAPIを前提としない。
- GitHubはソースの変更履歴と公開前のHTML生成・レビューに使う。www2からGitHubへリクエストしたり、GitHub内のJSONを読み込んだりしない。

## 初回公開（手動の安全な方法）

1. 国語研Web管理担当に `https://www2.ninjal.ac.jp/lingfes/` の公開可否・URLとファイル配置先・更新方法を確認し、承認を得る。
2. `data/` の発表・参加申込URLを確定し、GitHubで編集した内容に合わせて `python3 scripts/build_site.py` を実行。
3. `python3 scripts/validate_site.py` で全リンク・見出しアンカーとJavaScript不使用を確認。
4. `public/` の**中身だけ**を公開先 `/lingfes/` にコピーする。`src/`, `data/`, `scripts/`, `.github/` は公開しない。
5. `https://www2.ninjal.ac.jp/lingfes/`、`.../2027/`、過年度ページを表示・リンク・印刷確認。発表情報の登録後は、生成されたプログラム・地図も確認する。
6. 不要な個人情報・非公開PDF・試験用の架空データを含まないことを確認。

公開対象は生成済みの `.html` と `.css` です。GitHub Pages用 `.nojekyll` はwww2では不要なら省略できます。現在、発表データがないため2027年のプログラム・地図は生成しません。

## GitHub Pagesプレビュー

`.github/workflows/preview-pages.yml` は、`main` 更新時に Python で公開HTMLを生成してからプレビューサイトに配置します。**プレビューにもJavaScriptを置きません。** GitHub Pagesは www2 上のディレクトリを作成できません。

## GitHub Actionsからの本番同期（任意、初期状態は無効）

- `.github/workflows/deploy-ninjal.yml` は `vars.ENABLE_NINJAL_DEPLOY` が `true` の場合のみ実行されます。
- 国語研Web管理担当の明示的承認があり、GitHubランナーから公開ホストへSSH/SFTP接続できる場合のみ有効化します。
- Environment `ninjal-web` に必要なSecretsは `NINJAL_SSH_HOST`、`NINJAL_SSH_PORT`、`NINJAL_SSH_USER`、`NINJAL_SSH_PRIVATE_KEY`、`NINJAL_SSH_KNOWN_HOSTS`、`NINJAL_DEPLOY_PATH`。秘密鍵はリポジトリのファイルとして保存しないでください。
- `NINJAL_DEPLOY_PATH` は管理者が定める絶対パスで、末尾 `/lingfes/` とします。`--delete` は使いません。
- 機関外ランナーの接続が認められない場合は、管理者側の内部同期または手動転送とします。

例（実際のホスト名・パスは機関管理者が指定）：

```sh
python3 scripts/build_site.py
python3 scripts/validate_site.py
rsync -av public/ approved-user@example.host:/approved/www/lingfes/
```

## 公開ファイルの仕様

```text
/lingfes/index.html
/lingfes/assets/styles.css
/lingfes/2021/index.html ～ /lingfes/2026/index.html
/lingfes/2027/index.html
# 発表データ登録後にのみ生成：
/lingfes/2027/program.html
/lingfes/2027/map-a.html ～ /lingfes/2027/map-c.html
```

www2側で必要なのは通常の静的ファイル配信のみ。時間帯の地図選択、発表詳細への移動、PDFへのリンクはHTMLの `<a href="...">` のみを利用します。

## 既存ファイルの取扱い

`rsync` には `--delete` を付けず、公開許諾済みPDFなどの既存ファイルを保護します。このため、前回公開済みの空のプログラムや地図がサーバーに残っている場合は、管理者が該当する4つのHTMLファイルだけを個別に確認して削除してください。

## 2027年参加申込リンクの設定

`data/site-2027.json` の `online_participation_url`、`ninjal_onsite_20270327_url`、`onsite_20270328_url` にそれぞれ正式なURLを記入します。空欄の場合は対応するボタンを表示しません。2日間の申込・定員・参加者集計は独立して管理してください。2027年3月27日はオンライン開催で、国語研からの参加枠は限定人数です。3月28日は現地参加のみで、別途募集します。
