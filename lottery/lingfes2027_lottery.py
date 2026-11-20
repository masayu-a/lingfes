#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""言語学フェス2027 ブース抽選・Reject・フェスギャラリー振分け (Colab / Mac)

【今回の重要な区別】
  Reject（抽選・資料掲載の両方から除外）
    ・MULTIPLE_APPLICATION_REJECT_IDS: 多重申込として確認済みの受付番号
    ・TEST_REGISTRATION_REJECT_IDS: 運営による試験用の受付番号

  ギャラリー移動（Rejectではない。ブース抽選だけから除外）
    ・同じA/B/Cの枠で、一人でも共著者が重なる場合、最後の申込だけ
      ブース抽選に残し、先の申込はフェス・ギャラリーに移す。
    ・COAUTHOR_GALLERY_MOVE_IDS: 事務局が明示的に移動指定した申込
    ・AとCなど、枠が異なる場合には同じ著者が重複してもよい。

  抽選対象
    ・上記を除いた申込に対し、A/B/C各枠で次の文字列を計算する。
        lingfes2027|A|58123.45|0001
      SHA-256の16進64桁の昇順で並べ、各枠の上位36件をブースへ。
      定員超過の残りは繰上げ候補であり、ギャラリーにも回る。

【公開の安全性】
  ・公開用HTMLには申込番号、枠、結果だけを掲載。著者名・連絡先は載せない。
  ・web_public/ は公開用ファイルのみを集めたフォルダ。内部原簿はコピーしない。
  ・多重申込Rejectは番号と事由を公開し、試験登録の番号は原則公開しない。
  ・PREVIEW（予行演習）では『公開不可』を表示。確認前に配布しない。
  ・事務局指定リスト、最後のID、応募原簿は株価確定前に凍結する。
  ・Yahoo Financeの取得値は本番公表前に公表元の終値と必ず照合する。
"""

from __future__ import annotations

# ===========================================================================
# 1. 設定: 普段変更するのは原則としてこの欄のみ
# ===========================================================================

# [重要] 最大の申込番号。001〜この数字までを扱う。全枠通算。
# 例: 500 → 0001〜0500 が発行されうる。欠番があっても問題ない。
MAX_APPLICATION_NUMBER = 150

# 実際に受け付けた「最後の申込番号」。入力欄の意味を明確にするため
# LAST_PRESENTER_ID という名前にしているが、個々の著者IDではなく
# A/B/C通算のフォーム受付番号である（例: 0127 → 127番まで受け付けた）。
# MAX_APPLICATION_NUMBER はプログラムの上限、こちらは実際の締切時点。
LAST_PRESENTER_ID = 150

# ================================================================
# 受付の手動判定リスト：要素は4桁文字列（整数 12 でも可）。
# 実務では事務局で事由を確認したうえで番号を登録する。
# 重複する番号を複数のリストに書くとプログラムは停止する。
# ================================================================

# ① 多重申込等により、資料掲載も含め完全にRejectする番号。
#    この番号・理由は、公開用HTMLの「Reject一覧」に掲載する。
#    共著者が重なるだけの場合はここに入れない（下のギャラリー規則）。
MULTIPLE_APPLICATION_REJECT_IDS = []

# ② 自動判定とは別に、共著申込をギャラリーへ移す指定番号。
#    ここにある申込はRejectではなく、資料展示枠に残る。
#    自動判定で見つかる共著者重複は書かなくても移動される。
COAUTHOR_GALLERY_MOVE_IDS = []

# ③ 入力フォームの動作確認など、試験用として登録した番号。
#    抽選・ギャラリーともに対象外。番号自体は公開ページへ出さない。
TEST_REGISTRATION_REJECT_IDS = []

# ④ 公開ページの発表タイトルを表示するか。
#    Rejectや重複判定が含まれるので、公開の了承が取れるまでFalse推奨。
PUBLIC_INCLUDE_TITLES = False

# 各コアタイムのブース上限（現在は各36件）
BOOTH_CAPACITY = 36

# "demo" または "csv" を指定する。
# demo: 0001〜MAX_APPLICATION_NUMBER の架空の申込をA/B/Cに順番に割り当てる。
#       まず動作を確認するためのモードで、実際の採否ではない。
# csv : 実際のCSVに登録されている申込だけを抽選対象にする。
INPUT_MODE = "demo"

# INPUT_MODE="csv" の場合、CSVを置いたパス。
# Google Colabでは空文字のままにするとアップロード画面が開く。
# Macでは、例: "/Users/masayu-a/Downloads/applications.csv" と設定する。
CSV_PATH = ""

# "auto" | "preview" | "final" (詳細は先頭の説明を参照)
MODE = "auto"

# 本番で使う日付。2027年2月2日（火）の日経平均終値。
FINAL_PRICE_DATE = "2027-02-02"

# 日経平均終値は日本時間15:30ごろに確定するが、データ配信遅延を考慮し
# 日本時間16:00以降を、その日の終値を使用できる目安とする。
# 16:00以降でもデータが未到着の場合、本番ではエラーとする。
CLOSE_READY_HOUR = 16

# ファイルの保存先。Colabでは /content 以下、Macでは実行ディレクトリ以下。
OUTPUT_DIR_NAME = "lingfes2027_lottery_results"

# ===========================================================================
# 2. ライブラリ: 以下は通常変更不要
# ===========================================================================
import csv
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Asia/Tokyo")
SLOTS = ("A", "B", "C")
HASH_PREFIX = "lingfes2027"


def canonical_author(raw: str) -> str:
    """著者名の比較用正規化。

    例: '山田 太郎' と '山田　太郎' を同じとして扱う。
    ただし同姓同名は機械的に区別できない。実運用では著者IDの使用を推奨。
    CSVに著者IDを入れる場合も、区切り文字は半角セミコロン ; とする。
    """
    normalized = unicodedata.normalize("NFKC", raw).casefold()
    return re.sub(r"\s+", "", normalized)


def split_authors(value: str) -> list[str]:
    """著者欄（例: '山田太郎;佐藤花子'）をリストに変換する。"""
    # 全角セミコロンも許可。カンマ区切りは外国人名と混同するため非推奨。
    authors = [x.strip() for x in value.replace("；", ";").split(";")]
    authors = [x for x in authors if x]
    if not authors:
        raise ValueError("著者が空欄の申込は抽選に含められません")
    # 同一申込内の重複著者名は1人として扱う。
    return list(dict.fromkeys(authors))


def id_string(value: object) -> str:
    """申込番号を4桁に統一する。A/B/Cの枠名は申込番号に付けない。"""
    s = str(value).strip()
    # Excel経由で '1.0' に変化した数字を静かに誤解釈しない。
    if not re.fullmatch(r"[0-9]{1,4}", s):
        raise ValueError(f"申込番号は1〜4桁の数字としてください: {value!r}")
    number = int(s)
    if not (1 <= number <= 9999):
        raise ValueError(f"申込番号は0001〜9999にしてください: {value!r}")
    if number > MAX_APPLICATION_NUMBER:
        raise ValueError(f"申込番号 {s} は MAX_APPLICATION_NUMBER={MAX_APPLICATION_NUMBER} を超えます")
    return f"{number:04d}"


def load_applications() -> list[dict]:
    """CSVを読み、全枠共通の申込番号で管理する。

    CSVの推奨列：application_no,slot,authors,title
    日本語の列名「申込番号,枠,著者,タイトル」も使用可能。

    注意：申込番号はフォーム受付順で通算して付けている必要がある。
    CSV上の並び順ではなく、申込番号の大きさで『最後』を判定する。
    """
    if INPUT_MODE == "demo":
        # 予行演習：0001=A、0002=B、0003=C、0004=A……とする。
        # 各申込で架空の著者を独立に設定する（重複応募がない標準例）。
        # A/C間の重複などを試す場合は、添付のsample_applications.csvを利用。
        return [
            {"application_no": f"{i:04d}",
             "slot": SLOTS[(i - 1) % 3],
             "authors": f"架空著者{i:04d}",
             "title": f"動作確認用申込{i:04d}"}
            for i in range(1, LAST_PRESENTER_ID + 1)
        ]

    if INPUT_MODE != "csv":
        raise ValueError("INPUT_MODE は 'demo' または 'csv' のみ指定できます")

    path = CSV_PATH
    if not path:
        # Colabのみアップロードダイアログを開く。
        try:
            from google.colab import files
        except ImportError as exc:
            raise RuntimeError("MacでCSVを使う場合はCSV_PATHにファイルパスを設定してください") from exc
        print("応募一覧CSVをアップロードしてください（個人情報を含むため、共有ノートブックに保存しないでください）。")
        uploaded = files.upload()
        if len(uploaded) != 1:
            raise ValueError("CSVは1ファイルだけアップロードしてください")
        path = next(iter(uploaded))

    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSVにヘッダー行がありません")
        aliases = {
            "application_no": ("application_no", "application_id", "申込番号", "受付番号"),
            "slot": ("slot", "枠", "コアタイム"),
            "authors": ("authors", "著者", "共著者を含む著者", "author_ids"),
            "title": ("title", "タイトル", "発表題目"),
        }
        names = {}
        for key, options in aliases.items():
            names[key] = next((n for n in options if n in reader.fieldnames), None)
            if key in ("application_no", "slot", "authors") and names[key] is None:
                raise ValueError(f"CSVに必要な列 {key} がありません。列名例: {options}")
        records = []
        for line_no, row in enumerate(reader, start=2):
            if not any(str(v or "").strip() for v in row.values()):
                continue
            r = {k: str(row.get(col, "") or "").strip() if col else "" for k, col in names.items()}
            try:
                r["application_no"] = id_string(r["application_no"])
                r["slot"] = r["slot"].upper()
                if r["slot"] not in SLOTS:
                    raise ValueError("枠はA/B/Cのいずれかにしてください")
                split_authors(r["authors"])
            except ValueError as exc:
                raise ValueError(f"CSV {line_no} 行目: {exc}") from exc
            records.append(r)
        return records


def validate_applications(records: list[dict]) -> None:
    """受付番号・枠・著者欄を検査する。勝手に番号を再採番しない。

    LAST_PRESENTER_ID は締切時点の最終受付IDを指定する。CSVにそれより
    大きい番号があれば黙って無視せず、設定の間違いとして停止する。
    多重Reject・試験登録についても、元の受付番号を消さずに記録を残す。
    """
    if not isinstance(MAX_APPLICATION_NUMBER, int) or not (1 <= MAX_APPLICATION_NUMBER <= 9999):
        raise ValueError("MAX_APPLICATION_NUMBER は1〜9999の整数にしてください")
    if not isinstance(LAST_PRESENTER_ID, int) or not (1 <= LAST_PRESENTER_ID <= MAX_APPLICATION_NUMBER):
        raise ValueError("LAST_PRESENTER_ID は1〜MAX_APPLICATION_NUMBERの整数にしてください")
    if not isinstance(BOOTH_CAPACITY, int) or not (1 <= BOOTH_CAPACITY <= 36):
        raise ValueError("BOOTH_CAPACITY は1〜36にしてください")
    if not records:
        raise ValueError("申込が0件です")
    ids = [id_string(r["application_no"]) for r in records]
    repeats = [item for item, n in Counter(ids).items() if n > 1]
    if repeats:
        raise ValueError(f"申込番号の重複があります（A/B/C通算なので不可）: {repeats[:10]}")
    for r in records:
        r["application_no"] = id_string(r["application_no"])
        if int(r["application_no"]) > LAST_PRESENTER_ID:
            raise ValueError(f"受付番号{r['application_no']}はLAST_PRESENTER_ID={LAST_PRESENTER_ID}を超えます")
        r["slot"] = r["slot"].upper()
        if r["slot"] not in SLOTS:
            raise ValueError(f"不正な枠: {r['slot']}")
        r["authors_list"] = split_authors(r["authors"])
        r["author_keys"] = {canonical_author(a) for a in r["authors_list"]}
        if "" in r["author_keys"]:
            raise ValueError(f"空の著者ID: {r['application_no']}")


def configured_lists(records: list[dict]) -> dict[str, set[str]]:
    """手動入力の3種類の番号リストを正規化・検証する。

    ミスを見逃すと公開抽選の対象者が変わるため、未存在IDや二重指定は
    許容しない。入力が不正なら株価を取りに行く前に中止する。
    """
    sources = {
        "multiple_reject": MULTIPLE_APPLICATION_REJECT_IDS,
        "coauthor_manual_gallery": COAUTHOR_GALLERY_MOVE_IDS,
        "test_reject": TEST_REGISTRATION_REJECT_IDS,
    }
    present = {r["application_no"] for r in records}
    groups: dict[str, set[str]] = {}
    seen: dict[str, str] = {}
    for name, raw in sources.items():
        if not isinstance(raw, (list, tuple, set)):
            raise ValueError(f"{name} はリスト形式で指定してください")
        group: set[str] = set()
        for item in raw:
            aid = id_string(item)
            if int(aid) > LAST_PRESENTER_ID:
                raise ValueError(f"{name} の {aid} は最終受付番号を超えています")
            if aid not in present:
                raise ValueError(f"{name} の {aid} は申込CSVに存在しません")
            if aid in group:
                raise ValueError(f"{name} で申込番号 {aid} が二重指定されています")
            if aid in seen:
                raise ValueError(f"{aid} は {seen[aid]} と {name} の両方に含まれます")
            group.add(aid)
            seen[aid] = name
        groups[name] = group
    return groups


def determine_validity(records: list[dict]) -> dict[str, object]:
    """Reject・ギャラリー移動・ブース抽選候補を区分する。

    順序の意味:
      ① 試験登録・多重Rejectを抽選母集団から除く。
      ② Reject以外の同一枠の著者を調べ、各著者について最後の受付番号を記録。
         後続応募と一人でも著者が重なる先の応募はギャラリーへ。
      ③ 事務局の「共著申込ブース移動」リストにある応募もギャラリーへ。
      ④ 残った応募だけをハッシュ抽選に入れる。

    ギャラリーへ移した申込はReject扱いにしない。また、ギャラリー移動した
    申込はキャンセルによるブース繰上げの対象にはならない。
    """
    manual = configured_lists(records)
    no_lottery = manual["multiple_reject"] | manual["test_reject"]
    latest_by_slot_author: dict[tuple[str, str], str] = {}
    for r in records:
        aid = r["application_no"]
        if aid in no_lottery:
            continue  # Rejectや試験登録の共著者は、正式応募の判定を妨げない
        for author in r["author_keys"]:
            key = (r["slot"], author)
            if key not in latest_by_slot_author or int(aid) > int(latest_by_slot_author[key]):
                latest_by_slot_author[key] = aid

    for r in records:
        aid = r["application_no"]
        r["last_conflicting_ids"] = sorted({
            latest_by_slot_author[(r["slot"], author)]
            for author in r["author_keys"]
            if (r["slot"], author) in latest_by_slot_author
            and int(latest_by_slot_author[(r["slot"], author)]) > int(aid)
        })
        if aid in manual["test_reject"]:
            r["status"] = "REJECT_TEST"
            reason = "試験用登録（抽選・ギャラリーとも対象外）"
        elif aid in manual["multiple_reject"]:
            r["status"] = "REJECT_MULTIPLE"
            reason = "多重申込によるReject（事務局確認済み）"
        elif aid in manual["coauthor_manual_gallery"]:
            r["status"] = "GALLERY_MANUAL"
            reason = "共著申込により事務局指定でフェス・ギャラリーへ移動"
            if r["last_conflicting_ids"]:
                reason += "; 後続受付 " + ",".join(r["last_conflicting_ids"])
        elif r["last_conflicting_ids"]:
            r["status"] = "GALLERY_COAUTHOR"
            reason = "同一枠の共著者重複：後続受付 " + ",".join(r["last_conflicting_ids"])
        else:
            r["status"] = "LOTTERY"
            reason = "ブース抽選対象"
        r["reason"] = reason
        # 既存版のmake_rankingが使っているvalidも更新して互換性を維持する。
        r["valid"] = r["status"] == "LOTTERY"
        r["invalid_reason"] = "" if r["valid"] else reason
    return {"manual": manual, "latest_by_slot_author": latest_by_slot_author}


def obtain_nikkei_close() -> tuple[str, str, str]:
    """Yahoo Financeの日経平均 (^N225) の日足から終値を自動取得。

    返り値: (日付 YYYY-MM-DD, 価格 xx.xx, 種別 PREVIEW/FINAL)

    【重要】決済の確定前の値や未来の値を採用しない。
    取引日16:00までは前営業日を含む直近の確定終値を採用する。
    土日・祝日は直前の取引日の終値を使う。
    FINALの場合は必ず2027-02-02の終値を要求し、値がなければ停止。

    使用するサービスはYahoo Financeの非公式データAPIなので、
    正式抽選前に公表元の終値と照合し、採用した値を確定・保存する。
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance がありません。Colabでは '%pip install yfinance' を実行してください") from exc

    now = datetime.now(TIMEZONE)
    today = now.date()
    official_date = date.fromisoformat(FINAL_PRICE_DATE)
    ready_today = now.time() >= time(CLOSE_READY_HOUR, 0)
    final_allowed = today > official_date or (today == official_date and ready_today)

    if MODE not in ("auto", "preview", "final"):
        raise ValueError("MODE は auto / preview / final のいずれか")
    if MODE == "final" and not final_allowed:
        raise RuntimeError(f"本番抽選は{FINAL_PRICE_DATE}の終値公表後に実行してください（日本時間16:00以降）")

    require_official = MODE == "final" or (MODE == "auto" and final_allowed)
    if require_official:
        reference_date = official_date
    else:
        reference_date = today if ready_today else today - timedelta(days=1)

    # yfinance.endは排他的なので対象日の翌日を指定する。
    # 20日程度取得しておけば休日が連続しても直近の取引日を取得できる。
    start = reference_date - timedelta(days=20)
    end = reference_date + timedelta(days=1)
    print(f"日経平均の終値を取得しています: ^N225  {start} 〜 {reference_date}")
    df = yf.download(
        "^N225", start=start.isoformat(), end=end.isoformat(),
        interval="1d", auto_adjust=False, progress=False,
        threads=False, multi_level_index=False, timeout=20,
    )
    if df is None or df.empty:
        raise RuntimeError("株価データを取得できませんでした。ネットワーク接続またはYahoo Financeの応答を確認してください")

    # 古い版のyfinanceがMultiIndexを返す場合の互換処理。
    close_col = df["Close"]
    if getattr(close_col, "ndim", 1) > 1:
        close_col = close_col.iloc[:, 0]
    candidates = []
    for timestamp, raw_value in close_col.items():
        d = timestamp.date() if hasattr(timestamp, "date") else date.fromisoformat(str(timestamp)[:10])
        if d > reference_date:
            continue
        try:
            v = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(v) or v <= 0:
            continue
        candidates.append((d, v))
    if not candidates:
        raise RuntimeError("対象期間の有効な日経平均終値がありません")

    price_date, value = max(candidates, key=lambda pair: pair[0])
    if not require_official and price_date != reference_date:
        print(f"[注意] {reference_date} の終値が取得できないため、直近の確定値 {price_date} を使います。休場日や配信遅延の可能性があります。")
    if require_official and price_date != official_date:
        raise RuntimeError(
            f"本番日 {official_date} の終値をまだ取得できません。"
            f"取得済みの最新日付は {price_date} です。後で再実行してください。"
        )

    # 株価の小数点以下2桁を文字列として固定。
    # この文字列が少しでも変わると全員のハッシュ値が変わるので必ず記録する。
    price = format(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), ".2f")
    return price_date.isoformat(), price, "FINAL" if require_official else "PREVIEW"


def sha256_for(slot: str, close_price: str, application_no: str) -> tuple[str, str]:
    """指定の厳密な入力規則でハッシュ値を作る。

    UTF-8入力: 'lingfes2027|A|58123.45|0001'
    戻り値: (元文字列, 64桁16進数ハッシュ)
    ※ 株価の日付はハッシュ文字列には含めない（別途結果ファイルに記録）。
    """
    source = f"{HASH_PREFIX}|{slot}|{close_price}|{application_no}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return source, digest


def make_ranking(records: list[dict], price_date: str, close_price: str, phase: str) -> list[dict]:
    """A/B/Cで独立にSHA-256を昇順で並べる。"""
    out = []
    for slot in SLOTS:
        members = [r for r in records if r["slot"] == slot and r["valid"]]
        for r in members:
            r["hash_input"], r["sha256"] = sha256_for(slot, close_price, r["application_no"])
        # 64桁の16進数は辞書順＝数値の大小順になる。完全一致時は申込番号昇順。
        members.sort(key=lambda r: (r["sha256"], r["application_no"]))
        for i, r in enumerate(members, start=1):
            out.append({
                "phase": phase, "price_date": price_date, "nikkei_close": close_price,
                "slot": slot, "application_no": r["application_no"],
                "rank": i, "result": "ブース割当候補" if i <= BOOTH_CAPACITY else "ギャラリー・繰上げ候補",
                "sha256": r["sha256"], "hash_input": r["hash_input"],
                "authors": r["authors"], "title": r.get("title", ""),
            })
    return out


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    # utf-8-sig (BOM付き) はExcelで日本語が文字化けしにくい。
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _review_row(r: dict) -> dict:
    """内部台帳を作る。内部台帳には著者名・題目が入るので公開厳禁。"""
    return {
        "application_no": r["application_no"],
        "slot": r["slot"],
        "status": r["status"],
        "reason": r["reason"],
        "last_conflicting_ids": ";".join(r.get("last_conflicting_ids", [])),
        "authors": r["authors"], "title": r.get("title", ""),
    }


def make_public_html(records: list[dict], ranked: list[dict],
                     price_date: str, price: str, phase: str) -> str:
    """結果の公開用HTMLを生成。外部CSSやJavaScriptは一切必要ない。

    タイトル・著者名は原則出さない。入力フォームの個人情報も出さない。
    重複申込のRejectと、共著者重複でギャラリーへ移した応募は別節にする。
    試験登録者は公開する必要がないため、件数のみ（番号は非公開）。
    """
    from html import escape
    def esc(x: object) -> str:
        return escape(str(x), quote=True)
    def table(items: list[dict], columns: list[tuple[str, str]]) -> str:
        head = "".join(f"<th scope='col'>{esc(label)}</th>" for _, label in columns)
        if not items:
            return "<p>該当なし</p>"
        body = "".join(
            "<tr>" + "".join(f"<td>{esc(r.get(key,''))}</td>" for key, _ in columns) + "</tr>"
            for r in items
        )
        return f"<div class='scroll'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"

    def public_row(r: dict) -> dict:
        return {"application_no": r["application_no"], "slot": r["slot"],
                "title": r.get("title", "") if PUBLIC_INCLUDE_TITLES else ""}

    def public_rank(r: dict) -> dict:
        return {"application_no": r["application_no"], "slot": r["slot"],
                "rank": r["rank"], "sha256": r["sha256"],
                "title": r.get("title", "") if PUBLIC_INCLUDE_TITLES else ""}

    cols = [("slot", "枠"), ("application_no", "申込番号")]
    if PUBLIC_INCLUDE_TITLES:
        cols.append(("title", "題目"))
    rejects = [public_row(r) for r in records if r["status"] == "REJECT_MULTIPLE"]
    coauthors = [public_row(r) for r in records if r["status"] in ("GALLERY_COAUTHOR", "GALLERY_MANUAL")]
    booths = [public_rank(r) for r in ranked if r["result"] == "ブース割当候補"]
    overflow = [public_rank(r) for r in ranked if r["result"] != "ブース割当候補"]
    rcols = [("slot", "枠"), ("application_no", "申込番号"), ("rank", "抽選順位")]
    if PUBLIC_INCLUDE_TITLES:
        rcols.append(("title", "題目"))
    preview = phase != "FINAL" or INPUT_MODE != "csv"
    notice = ("これは予行演習の出力です。正式な採否として公開しないでください。"
              if preview else "本番用の計算結果です。公表前に日経平均の公式終値と受付原簿を照合してください。")
    summary = " / ".join(
        f"{slot}枠: 抽選対象{sum(r['slot']==slot and r['status']=='LOTTERY' for r in records)}件"
        for slot in SLOTS
    )
    return f"""<!doctype html>
<html lang='ja'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width, initial-scale=1'>
{'<meta name="robots" content="noindex,nofollow">' if preview else ''}
<title>言語学フェス2027 ブース抽選結果</title>
<style>
:root{{--bg:#f6f8fb;--text:#172b41;--line:#ccd8e3;--navy:#17435b}}
*{{box-sizing:border-box}} body{{font-family:system-ui,'Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif;background:var(--bg);color:var(--text);line-height:1.7;margin:0}}
main{{max-width:980px;margin:auto;padding:28px 22px 70px}}
h1{{font-size:1.8rem}}h2{{border-bottom:2px solid var(--line);padding-bottom:7px;margin-top:38px;font-size:1.25rem}}
.notice{{padding:15px;background:#fff0db;border-left:4px solid #b57c22;font-weight:700}}
.small{{color:#4a6275;font-size:.9rem}}.scroll{{max-width:100%;overflow:auto}}
table{{border-collapse:collapse;width:100%;background:white;margin-top:10px}}
th,td{{border-bottom:1px solid var(--line);text-align:left;padding:7px 10px}}
th{{background:#e7eef5;color:var(--navy)}}
</style></head><body><main>
<h1>言語学フェス2027 ブース抽選結果</h1>
<p class='notice'>{esc(notice)}</p>
<p>使用した日経平均終値：<strong>{esc(price_date)} / {esc(price)}円</strong>。
抽選順位は <code>lingfes2027|枠|終値|4桁受付番号</code> のSHA-256を昇順に並べたものです。</p>
<p class='small'>最終受付番号：{esc(f'{LAST_PRESENTER_ID:04d}')} / {esc(summary)}</p>
<h2>ブース割当候補（各枠最大{esc(BOOTH_CAPACITY)}件）</h2>
{table(booths, rcols)}
<h2>ブース満席によるギャラリー・繰上げ候補</h2>
<p class='small'>ブース採択者の辞退があった場合、下記の順位に従って繰り上げます。</p>
{table(overflow, rcols)}
<h2>共著申込によるフェス・ギャラリー移動</h2>
<p class='small'>同一枠内で共著者が重複するため、最後の申込のみブース抽選に残しました。
下記の発表はRejectではなく資料展示枠です（ブース繰上げ対象外）。</p>
{table(coauthors, cols)}
<h2>多重申込によるReject一覧</h2>
<p class='small'>事務局が多重申込として確認し、抽選およびギャラリーへの掲載対象から除外した番号です。</p>
{table(rejects, cols)}
<p class='small'>別途、試験登録 {sum(r['status']=='REJECT_TEST' for r in records)} 件を抽選対象から除外しました。試験用の申込番号は公開していません。</p>
</main></body></html>"""


def main() -> None:
    """全受付の分類→株価取得→ハッシュ順位→内部・公開用出力。"""
    print("=" * 74)
    print("言語学フェス2027 ブース抽選・重複ギャラリー移動・多重Reject")
    print("=" * 74)
    print(f"入力モード: {INPUT_MODE} / 株価モード: {MODE}")
    print(f"受付番号の上限: {MAX_APPLICATION_NUMBER:04d} / 最終受付ID: {LAST_PRESENTER_ID:04d}")
    if INPUT_MODE == "demo":
        print("[予行演習] 架空の登録者を作るモードです。抽選結果として公開できません")

    records = load_applications()
    validate_applications(records)
    details = determine_validity(records)
    records.sort(key=lambda r: int(r["application_no"]))
    counts = Counter(r["status"] for r in records)
    print(f"受付: {len(records)}件 / ブース抽選対象: {counts['LOTTERY']}件")
    print(f"多重Reject: {counts['REJECT_MULTIPLE']}件 / 試験Reject: {counts['REJECT_TEST']}件")
    print(f"共著重複ギャラリー移動: {counts['GALLERY_COAUTHOR'] + counts['GALLERY_MANUAL']}件")
    print("※ ギャラリー移動者はRejectではなく、発表資料を掲載する対象です")

    # 先に受付条件を検証してから、日経平均の終値を取得する。
    price_date, price, phase = obtain_nikkei_close()
    print(f"使用日経平均終値: {price_date} / {price}円 ({phase})")
    if phase == "FINAL":
        print("[要照合] Yahoo Finance取得値を公式の終値と照合してください")
    else:
        print("[予行演習] この出力を正式結果として公開しないでください")

    ranked = make_ranking(records, price_date, price, phase)
    print("順位: SHA-256 64桁16進文字列の昇順（A/B/Cごと）")
    for slot in SLOTS:
        in_slot = [r for r in ranked if r["slot"] == slot]
        print(f"  {slot}枠: 抽選対象{len(in_slot)} / ブース{min(len(in_slot), BOOTH_CAPACITY)} / 繰上げ{max(0, len(in_slot)-BOOTH_CAPACITY)}")

    outdir = Path.cwd() / OUTPUT_DIR_NAME
    outdir.mkdir(parents=True, exist_ok=True)
    allcols = ["phase", "price_date", "nikkei_close", "slot", "application_no", "rank", "result", "sha256", "hash_input", "authors", "title"]
    internalcols = ["application_no", "slot", "status", "reason", "last_conflicting_ids", "authors", "title"]
    pubcols = ["phase", "price_date", "nikkei_close", "slot", "application_no", "rank", "result", "sha256", "hash_input"]
    # 内部用CSVは著者名等を含むため www2 / GitHub public/ に置かない。
    write_csv(outdir / "全受付判定_内部用.csv", [_review_row(r) for r in records], internalcols)
    write_csv(outdir / "抽選順位_内部用.csv", ranked, allcols)
    write_csv(outdir / "ブース割当候補.csv", [r for r in ranked if r["result"] == "ブース割当候補"], allcols)
    write_csv(outdir / "定員超過_繰上げ候補_内部用.csv", [r for r in ranked if r["result"] != "ブース割当候補"], allcols)
    write_csv(outdir / "多重申込Reject_内部用.csv", [_review_row(r) for r in records if r["status"]=="REJECT_MULTIPLE"], internalcols)
    write_csv(outdir / "試験登録Reject_内部用.csv", [_review_row(r) for r in records if r["status"]=="REJECT_TEST"], internalcols)
    write_csv(outdir / "共著申込ギャラリー移動_内部用.csv", [_review_row(r) for r in records if r["status"] in ("GALLERY_COAUTHOR", "GALLERY_MANUAL")], internalcols)
    latest_rows = [
        {"slot": slot, "author_key": author, "last_application_no": aid}
        for (slot, author), aid in sorted(details["latest_by_slot_author"].items())
    ]
    write_csv(outdir / "共著者別_最後の発表者ID_内部用.csv", latest_rows, ["slot", "author_key", "last_application_no"])
    # Reject公開台帳には個人名・メール・題目を含めない。
    reject_public = [
        {"application_no": r["application_no"], "slot": r["slot"], "reason": "多重申込によるReject"}
        for r in records if r["status"] == "REJECT_MULTIPLE"
    ]
    write_csv(outdir / "多重申込Reject_公開用.csv", reject_public, ["application_no", "slot", "reason"])
    write_csv(outdir / "抽選検証用_匿名.csv", ranked, pubcols)
    # -------------------------------------------------------------------
    # Web公開向けのファイルだけを一つの独立したディレクトリにまとめる。
    # 出力フォルダのルートには著者名や内部審査事由が入ったCSVがあるので、
    # ルートを丸ごとWeb公開してはいけない。web_public/ のみを検討対象とする。
    # なお、PREVIEW/デモのページは公開不可なのでnoindex警告を表示する。
    # -------------------------------------------------------------------
    public_dir = outdir / "web_public"
    public_dir.mkdir(parents=True, exist_ok=True)
    public_html = make_public_html(records, ranked, price_date, price, phase)
    (public_dir / "index.html").write_text(public_html, encoding="utf-8")
    write_csv(public_dir / "多重申込Reject一覧.csv", reject_public,
              ["application_no", "slot", "reason"])
    gallery_public = [
        {"application_no": r["application_no"], "slot": r["slot"], "category": "共著者重複によるギャラリー移動"}
        for r in records if r["status"] in ("GALLERY_COAUTHOR", "GALLERY_MANUAL")
    ]
    write_csv(public_dir / "共著者重複_ギャラリー移動一覧.csv", gallery_public,
              ["application_no", "slot", "category"])
    write_csv(public_dir / "抽選順位_匿名.csv", ranked, pubcols)
    # 公開用の条件ファイルにはReject・試験用IDリストや原簿ハッシュを含めない。
    public_meta = {
        "phase": phase,
        "input_mode": INPUT_MODE,
        "price_date": price_date,
        "nikkei_close": price,
        "hash_template": "lingfes2027|{slot}|{nikkei_close_2dp}|{application_no_4d}",
        "sort_order": "ascending",
        "booth_capacity_per_slot": BOOTH_CAPACITY,
        "last_application_number": f"{LAST_PRESENTER_ID:04d}",
        "counts": {s: {
            "lottery_eligible": sum(r["slot"] == s and r["status"] == "LOTTERY" for r in records),
            "booth_selected": sum(r["slot"] == s and r["result"] == "ブース割当候補" for r in ranked),
            "coauthor_gallery": sum(r["slot"] == s and r["status"] in ("GALLERY_COAUTHOR", "GALLERY_MANUAL") for r in records),
            "multiple_reject": sum(r["slot"] == s and r["status"] == "REJECT_MULTIPLE" for r in records),
        } for s in SLOTS},
        "note": "予行演習の結果は正式公表不可。正式公表前に株価と受付情報を確認すること。"
    }
    (public_dir / "抽選条件_公開用.json").write_text(
        json.dumps(public_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 受付原簿や内部判定リストの改変を検出するために固定ハッシュを残す。
    # この値自体は氏名などを公開しない（ただし元データは安全に保存する）。
    application_fingerprint = hashlib.sha256("\n".join(
        f"{r['application_no']}|{r['slot']}|{';'.join(sorted(r['author_keys']))}|{r.get('title','')}|{r['status']}"
        for r in records
    ).encode("utf-8")).hexdigest()
    selection_input = "\n".join([
        f"LAST_PRESENTER_ID={LAST_PRESENTER_ID}",
        f"MAX_APPLICATION_NUMBER={MAX_APPLICATION_NUMBER}",
        f"BOOTH_CAPACITY={BOOTH_CAPACITY}",
    ] + [f"{key}={','.join(sorted(ids))}" for key, ids in sorted(details["manual"].items())])
    metadata = {
        "lottery_rule": "lingfes2027|{slot}|{nikkei_close_2dp}|{application_no_4d} -> SHA256 -> ascending",
        "run_at_jst": datetime.now(TIMEZONE).isoformat(),
        "phase": phase, "input_mode": INPUT_MODE,
        "price_date": price_date, "nikkei_close": price,
        "price_source": "Yahoo Finance (^N225), daily Close, auto_adjust=False",
        "scheduled_final_price_date": FINAL_PRICE_DATE,
        "max_application_number": MAX_APPLICATION_NUMBER,
        "last_presenter_id": f"{LAST_PRESENTER_ID:04d}",
        "booth_capacity_per_slot": BOOTH_CAPACITY,
        "manual_lists": {key: sorted(ids) for key, ids in details["manual"].items()},
        "categories": dict(sorted(counts.items())),
        "counts_by_slot": {slot: {
            "lottery": sum(r["slot"]==slot and r["status"]=="LOTTERY" for r in records),
            "booths": sum(r["slot"]==slot and r["result"]=="ブース割当候補" for r in ranked),
            "coauthor_gallery": sum(r["slot"]==slot and r["status"] in ("GALLERY_COAUTHOR", "GALLERY_MANUAL") for r in records),
        } for slot in SLOTS},
        "sha256_private_application_decisions": application_fingerprint,
        "sha256_manual_control_settings": hashlib.sha256(selection_input.encode("utf-8")).hexdigest(),
        "notes": "共著者の重複は同一コアタイム内のみ。ギャラリー移動はRejectではない。予行演習ページを本番として公開しない。",
    }
    (outdir / "抽選実行条件.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"\n結果の保存先: {outdir}")
    for file in sorted(outdir.iterdir()):
        print(" -", file.name)
    print(f"[Web公開候補] {public_dir} 以下だけを個別確認してください")
    print("[注意] 内部用CSVをWebサイトにアップロードしないでください")

    # Colabなら一式をZIPとしてまとめてローカルへダウンロード。
    # （ZIPには内部情報が含まれるので、そのままWeb公開しない）
    try:
        from google.colab import files
        import shutil
    except ImportError:
        pass
    else:
        archive = shutil.make_archive(str(outdir), "zip", root_dir=outdir)
        print("Colabから内部用結果ZIPをダウンロード:", archive)
        files.download(archive)
        public_archive = shutil.make_archive(str(outdir) + "_web_public", "zip", root_dir=public_dir)
        print("Colabから公開用のみのZIPをダウンロード:", public_archive)
        files.download(public_archive)


if __name__ == "__main__":
    main()
