# 言語学フェス2027 FAQ編集・公開ガイド

## FAQの掲載場所

`https://www2.ninjal.ac.jp/lingfes/2027/#faq` を予定しています。

GitHub上の編集元は `src/2027/index.html` の `<section id="faq">` です。`scripts/build_site.py` が `public/2027/index.html` を自動生成しますので、**恒久的な更新は必ず `src/2027/index.html` に行ってください**。生成済み `public/` のみを編集すると次のビルドで変更が失われます。

問い合わせフォームは同ページの `#contact` に埋め込まれています。ページ内リンクでフォームに移動できます。

## FAQを一件追加するためのHTMLテンプレート

既存の `<div class="grid2">` の内側、最後の `</div>` の直前に次のブロックを貼ります。

```html
<div class="panel">
  <div class="eyebrow">参加申込・会場案内</div>
  <h3>質問の文章を記載しますか？</h3>
  <p>回答の文章を記載します。必要があれば<a href="https://example.org/">関連資料</a>にリンクします。</p>
</div>
```

カテゴリ例：発表申込・資料提出／参加申込・会場案内／抽選・採択／問い合わせとFAQ／安全に関する相談／その他。

## 公開前チェック

- FAQへの公開に同意された問い合わせだけを候補とし、同意していても自動掲載せず事務局が編集・確認する。
- 氏名、メールアドレス、受付番号、具体的な人物・所属等、本人や第三者を特定する情報を掲載しない。
- 質問を必要に応じて一般化し、個人に関する事実・推測を記載しない。
- ハラスメント・参加上の安全に関する相談は、同意の有無に関わらずFAQには掲載しない。個別の担当者で管理する。
- 回答の内容、開催日程、申込URL、規定等が現時点の公式情報と一致するか確認する。
- 不要な内部情報や個人情報をGitHub・publicへコミットしない。

## 反映方法

1. `src/2027/index.html` の `#faq` にFAQを追記してコミット。
2. GitHub Actions の Generate and commit public HTML により公開HTMLが再生成される（必要に応じてワークフロー実行を確認）。
3. `public/2027/index.html` に追加内容が含まれることを確認。
4. `www2.ninjal.ac.jp/lingfes/` への反映は、国語研Web管理担当が承認する方法で行う。**GitHubへの反映と本番公開は別工程。**

## フォームURL

直接リンク：

https://forms.cloud.microsoft/Pages/ResponsePage.aspx?id=WgYfnQMt70Gf98AUO1nLLAkLOaIRaiNJlRKh9BAqswtUREw1WEJPNkhHU0k2REtNWTVCU003TjlYNi4u

埋め込み：`src/2027/index.html` の `<section id="contact">` を修正してください。
