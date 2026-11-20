#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""言語学フェス2027 公開数値を利用したブース抽選 (Google Colab / Mac)

【抽選の考え方】
  1. A/B/Cの発表枠にかかわらず、申込番号は受付順で通算して発行する。
     例: 0001=A, 0002=C, 0003=B, 0004=A。4桁・ゼロパディング。
  2. 同じ枠内で共通の著者を含む応募が複数ある場合、受付番号が大きいもの
     （＝最後の申込）だけがその著者について有効となる。
     ※ A枠とC枠（またはB枠）との間では、このルールを適用しない。
        同一著者がAとCでそれぞれ発表してよい。
  3. 有効な応募に対して、日経平均株価の終値を自動取得し、次の文字列を作る。
        lingfes2027|A|58123.45|0001
     これをUTF-8でSHA-256ハッシュ化する（価格は例示用・架空）。
  4. A/B/Cを個別に、SHA-256の16進数表記を「昇順」に並べる。
     各枠の上位36件がブース割当候補、それ以降は繰上げ候補／ギャラリー候補。

【試行と本番】
  MODE='auto'  : 2027年2月2日の終値が確定する前は、直近で確定した終値で
                 何度でも予行演習。2027年2月2日の日本時間16時以降は、
                 同日の日経平均終値を厳密に取得して本番抽選。
  MODE='preview': いつでも直近の確定終値を使う予行演習。
  MODE='final'  : 2027年2月2日の終値のみを使い、未公表ならエラーにする。

【注意】
  ・抽選前に受付番号と有効応募一覧を固定する。番号は後から振り直さない。
  ・同一人物の表記ゆれを避けるため、著者欄は可能なら一意の著者IDで管理する。
  ・Yahoo Finance (^N225) 取得値は、確定前に公式公表値と照合する。
  ・匿名の結果一覧であっても応募IDの公開方法は個人情報保護を考慮する。
  ・これは抽選用コードであり、個人情報を外部サービスに送信しない。
    外部から取得するのは日経平均の株価のみ。
"""

from __future__ import annotations

# ===========================================================================
# 1. 設定: 普段変更するのは原則としてこの欄のみ
# ===========================================================================

# [重要] 最大の申込番号。001〜この数字までを扱う。全枠通算。
# 例: 500 → 0001〜0500 が発行されうる。欠番があっても問題ない。
MAX_APPLICATION_NUMBER = 150

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
            for i in range(1, MAX_APPLICATION_NUMBER + 1)
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
    """入力の全枠通算IDを検証する。"""
    if not 1 <= MAX_APPLICATION_NUMBER <= 9999:
        raise ValueError("MAX_APPLICATION_NUMBER は1〜9999にしてください（4桁方式）")
    if not 1 <= BOOTH_CAPACITY <= 36:
        raise ValueError("BOOTH_CAPACITY は1〜36にしてください")
    if not records:
        raise ValueError("申込が0件です")
    ids = [r["application_no"] for r in records]
    repeats = [item for item, n in Counter(ids).items() if n > 1]
    if repeats:
        raise ValueError(f"申込番号の重複があります（A/B/C通算なので不可）: {repeats[:10]}")
    for r in records:
        # demoにもcsvにも同じルールを適用する。
        r["application_no"] = id_string(r["application_no"])
        if r["slot"] not in SLOTS:
            raise ValueError(f"不正な枠: {r['slot']}")
        r["authors_list"] = split_authors(r["authors"])
        r["author_keys"] = {canonical_author(a) for a in r["authors_list"]}
        if "" in r["author_keys"]:
            raise ValueError(f"空の著者ID: {r['application_no']}")


def determine_validity(records: list[dict]) -> None:
    """同じ枠で著者が重複するとき、各著者にとって最後の申込のみ有効。

    この『最後』は数値の申込番号で決まる。枠Aの著者が枠Cにも参加していても、
    Aの応募もCの応募も相互に無効にはならない。

    例：
       0001: A, 著者X;著者Y
       0005: A, 著者X
       0010: C, 著者Y
    なら0001はAで無効、0005はAで有効、0010はCで有効。

    同じ枠の後続申込に著者が一人でも重なる場合、その前の申込全体を無効とする。
    """
    latest_by_slot_author: dict[tuple[str, str], int] = {}
    for r in records:
        k = int(r["application_no"])
        for author_key in r["author_keys"]:
            key = (r["slot"], author_key)
            latest_by_slot_author[key] = max(k, latest_by_slot_author.get(key, 0))

    for r in records:
        k = int(r["application_no"])
        conflicting_later = sorted({
            latest_by_slot_author[(r["slot"], author_key)]
            for author_key in r["author_keys"]
            if latest_by_slot_author[(r["slot"], author_key)] > k
        })
        r["valid"] = not conflicting_later
        r["invalid_reason"] = (
            "同じ枠の後続申込 " + ",".join(f"{n:04d}" for n in conflicting_later)
            + " に共通著者がいるため無効"
            if conflicting_later else ""
        )


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


def main() -> None:
    """本体の一連の流れ。実行内容を画面表示し、ファイルへ保存する。"""
    print("=" * 74)
    print("言語学フェス2027 ブース抽選（申込番号4桁・A/B/C通算・枠内のみ重複無効）")
    print("=" * 74)
    print(f"入力モード: {INPUT_MODE} / 抽選モード: {MODE}")
    print(f"最大申込番号: {MAX_APPLICATION_NUMBER:04d} / 1枠のブース上限: {BOOTH_CAPACITY}")
    if INPUT_MODE == "demo":
        print("[注意] デモデータによる予行演習です。実際の採否には利用できません。")

    records = load_applications()
    validate_applications(records)
    determine_validity(records)
    records.sort(key=lambda r: int(r["application_no"]))
    valid = [r for r in records if r["valid"]]
    invalid = [r for r in records if not r["valid"]]

    # 先に応募データの重複処理結果を確認し、後から株価を取得する。
    print(f"全枠通算申込: {len(records)}件 / 有効: {len(valid)}件 / 枠内著者重複による無効: {len(invalid)}件")
    print("有効内訳: " + ", ".join(f"{slot}={sum(r['slot'] == slot for r in valid)}" for slot in SLOTS))

    price_date, price, phase = obtain_nikkei_close()
    print(f"使用する日経平均終値: {price_date}  {price}円 ({phase})")
    if phase == "PREVIEW":
        print("[予行演習] この日の結果は採否の確定結果ではありません。株価が変われば順位も変わります。")
    else:
        print("[本番条件] 指定日の日経平均終値を取得しました。公式値と照合してから公表してください。")

    ranked = make_ranking(records, price_date, price, phase)
    print("抽選順位: SHA-256 16進数・昇順（小さい順）")
    for slot in SLOTS:
        rs = [r for r in ranked if r["slot"] == slot]
        print(f"  {slot}枠: 有効{len(rs)}件 / ブース候補{min(len(rs), BOOTH_CAPACITY)}件 / ギャラリー・繰上げ候補{max(0,len(rs)-BOOTH_CAPACITY)}件")
        print("       先頭5件: " + ", ".join(x["application_no"] for x in rs[:5]))

    outdir = Path.cwd() / OUTPUT_DIR_NAME
    outdir.mkdir(parents=True, exist_ok=True)

    allcols = ["phase", "price_date", "nikkei_close", "slot", "application_no", "rank", "result", "sha256", "hash_input", "authors", "title"]
    write_csv(outdir / "抽選順位_内部用.csv", ranked, allcols)
    write_csv(outdir / "ブース割当候補.csv", [r for r in ranked if r["result"] == "ブース割当候補"], allcols)
    write_csv(outdir / "ギャラリー・繰上げ候補.csv", [r for r in ranked if r["result"] != "ブース割当候補"], allcols)
    # 無効申込には原因を残す。抽選順位を付けない。
    invalid_rows = [
        {"slot": r["slot"], "application_no": r["application_no"],
         "authors": r["authors"], "title": r.get("title", ""), "reason": r["invalid_reason"]}
        for r in invalid
    ]
    write_csv(outdir / "無効申込_内部用.csv", invalid_rows, ["slot", "application_no", "authors", "title", "reason"])
    # 個人名を含まない検証用ファイル。
    publiccols = ["phase", "price_date", "nikkei_close", "slot", "application_no", "rank", "result", "sha256", "hash_input"]
    write_csv(outdir / "抽選検証用_匿名.csv", ranked, publiccols)

    metadata = {
        "rule": "lingfes2027|{slot}|{nikkei_close_2dp}|{application_no_4d} -> SHA256 -> ascending",
        "sha256_sort_order": "ascending",
        "run_at_jst": datetime.now(TIMEZONE).isoformat(),
        "phase": phase, "input_mode": INPUT_MODE, "final_price_date": FINAL_PRICE_DATE,
        "price_date": price_date, "nikkei_close": price, "price_source": "Yahoo Finance (^N225), daily Close, auto_adjust=False",
        "max_application_number": MAX_APPLICATION_NUMBER, "booth_capacity_per_slot": BOOTH_CAPACITY,
        "duplicate_rule": "invalidate older applications sharing ANY author WITHIN the SAME slot only; largest numeric application number is last",
        "total": len(records), "valid": len(valid), "invalid": len(invalid),
        "counts_by_slot": {s: {"valid": sum(r["slot"] == s for r in valid),
                               "selected": sum(r["slot"] == s and r["result"] == "ブース割当候補" for r in ranked)} for s in SLOTS},
        "sha256_of_eligible_id_slot_list": hashlib.sha256(
            "\n".join(f"{r['application_no']}|{r['slot']}|{'1' if r['valid'] else '0'}" for r in records).encode("utf-8")
        ).hexdigest(),
        # 個人情報を含む完全な内部原簿のハッシュ。ハッシュ値のみを公表する場合も
        # 応募者一覧の保管・閲覧権限には注意。内部原簿を勝手に公表しないこと。
        "sha256_of_private_master_list": hashlib.sha256(
            "\n".join(
                f"{r['application_no']}|{r['slot']}|{';'.join(sorted(r['author_keys']))}|{r.get('title','')}|{'1' if r['valid'] else '0'}"
                for r in records
            ).encode("utf-8")
        ).hexdigest(),
    }
    (outdir / "抽選実行条件.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"結果を保存しました: {outdir}")
    for f in sorted(outdir.iterdir()):
        print(f"  - {f.name}")
    print("[注意] 内部用CSVには著者名が含まれます。無条件に公開・コミットしないでください。")

    # Google Colabでは結果をZIPへまとめて一括ダウンロードできるようにする。
    try:
        from google.colab import files
        import shutil
    except ImportError:
        pass
    else:
        archive = shutil.make_archive(str(outdir), "zip", root_dir=outdir)
        print(f"Colabから結果ZIPをダウンロードします: {archive}")
        files.download(archive)


if __name__ == "__main__":
    main()
