# Mac: `web_public/` と `mirror-new2.sh` の同期

抽選コードの出力は、**Python実行時のカレントディレクトリ**にある
`lingfes2027_lottery_results/` へ作られます。

例えば、次のように実行した場合は

```sh
cd /Users/masayu-a/lingfes
python3 lottery/lingfes2027_lottery.py
```

Webに配置する候補は **次のフォルダの中身だけ**です。

```text
/Users/masayu-a/lingfes/lingfes2027_lottery_results/web_public/
```

同じ親ディレクトリの `全受付判定_内部用.csv` や `抽選実行条件.json` などには
内部情報が入るので、`lingfes2027_lottery_results/` を丸ごと rsync しないでください。

## 既存 `mirror-new2.sh` を使う場合

元の `mirror-new2.sh` のSSHログイン名・接続先・鍵設定はそのまま使い、
同期元を `.../lingfes2027_lottery_results/web_public/` に変更してください。
同期先は `www2` 上の **抽選専用のディレクトリ**にしてください。
既存の `/lingfes/index.html` を上書きしないためです。

この配布物の `examples/mirror-new2_lottery.example.sh` は、
`REMOTE_DEST` の設定を必須とする安全なひな形です。既存の
`~/mirror-new2.sh` を無条件に上書きせず、内容を見比べて取り込んでください。

本番公開前に `examples/publish_gate.py` で生成内容を承認すると、
各ファイルのSHA-256をまとめた承認ハッシュが出力ディレクトリの1階層上に
保存されます。同期ひな形は本番モード・CSV入力・承認ハッシュ一致を確認し、
内容が変われば転送を停止します。

```sh
python3 examples/publish_gate.py approve \
  /Users/masayu-a/lingfes/lingfes2027_lottery_results/web_public
```

上記は`lottery/`更新パッケージ内の`examples/`から実行する想定です。
本番用の日経平均終値、申込番号とRejectリストを人間が確認するまでは承認しないでください。

## cron（10分ごと）

macOSのユーザーcrontabは **5つの時刻フィールド**です。

```cron
SHELL=/bin/bash
PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin
*/10 * * * * /bin/bash /Users/masayu-a/mirror-new2.sh >> /Users/masayu-a/mirror-new2.log 2>&1
```

以前の `*/10 * * * * * bash ...` は `*` が1個多いので修正してください。
cronの行自体は、スクリプトのパスが変わらなければ変更する必要はありません。

注意： `web_public/` はGitHubの `lottery` ブランチには入れず、
Mac上で実際の応募CSVを読み込んで出力するものです。
GitHubから `git pull` しただけでは新しい抽選結果は生成されません。
