#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""言語学フェス2027：Microsoft Forms回答から行う3種類の公開抽選。

【何をするか】
  (1) Microsoft Forms「回答をExcelで開く」から取得した XLSX / CSV を読む。
      A・B・C通算の「ID」列を申込番号とする（1 -> 0001）。
  (2) 2027-02-01 12:00 JSTより前の回答だけを受付。新規／修正／取消を照合する。
      修正・取消は旧IDと主発表者の氏名・メールアドレスの一致が必須。
      以前の回答は消さずに内部の履歴に残し、最後の修正申込のみ有効。
  (3) 事務局指定の試験登録・多重Rejectを除外し、同一コアタイムの共著
      重複は最後の申込だけをブース抽選へ、古い申込をギャラリー対象にする。
  (4) 2027-02-01の日経平均終値を使い、ブース A/B/C を各36件選ぶ。
  (5) ブース採択者の希望者から、3月28日のポスター A/B/C を各8件選ぶ。
  (6) 3月27日現地配信はオンラインブース採択者を「人」単位で最大28席選ぶ。同一人物が
      A/C両方に申し込んでも1席。居室あり・実行委員は28席の定員外。
      現地ポスター採択者のうち希望者を優先し、残席を抽選する。
  (7) 全結果を事務局用CSVに、個人情報を除いた結果を web_public/ に出力。

【SHA-256の厳密な仕様】
  - 終値 : 例 58123.45（カンマなし、小数点以下2桁。架空の数字）
  - 申込番号 : 4桁ゼロパディング。例 1→0001、12→0012、123→0123
  - SHA-256(UTF-8文字列)の16進64桁表記を「昇順（小さい順）」に並べる。
  - ブース : lingfes2027|A|58123.45|0001
  - ポスター : lingfes2027|POSTER|A|58123.45|0001
  - 現地配信 : lingfes2027|ONSITE|58123.45|0001
    ※現地配信は1人1席。複数の有効申込がある場合は最小IDを代表IDとする。
    ※ハッシュ値が万一一致した場合は代表IDの昇順とする。

【予行演習／本番】
  - 締切 2027-02-01 12:00 JST。終値確定は同日午後（取引所は15:30まで）。
  - 本番判定は同日16:00 JST以降とし、その日の終値を厳密に要求する。
    取得できない場合は「前日終値」で代用せず停止する。
  - それ以前の実行は直近の確定済み終値で PREVIEW として動作する。
  - 取得元はYahoo Finance (^N225)。正式公表前には日経公式終値と照合。
  - 本番用フォーム回答Excel、試験登録／Rejectリストを終値判明前に固定。

【公開上の注意】
  - 入力Excelには氏名・メールアドレス・資料アップロードURLが含まれる。
    GitHubや公開サーバーに決して置かないこと。
  - web_public/ は匿名申込IDと判定だけ。試験登録のIDは公開しない。
  - PREVIEWは絶対に公表しない。web_publicの内容は事務局の承認後に公開。
  - このプログラムが扱う28席は、この発表申込フォームのオンラインブース採択者（主発表者）専用。
    ギャラリー対象者と一般参加のみの方は所内配信の抽選対象外。
    2月8日以降に募集する一般参加者は3月27日にはオンライン参加とし、
    3月28日の現地参加とは別管理とする。
"""
from __future__ import annotations

# ================== 設定：通常はこの部分だけ確認 ===========================
INPUT_FILE = ""                 # 空欄ならGoogle Colabでファイル選択。MacはCLI --input。
OUTPUT_DIR = "lingfes2027_lottery_results"
MODE = "auto"                  # auto / preview / final
MAX_APPLICATION_NUMBER = 9999  # 受付番号の上限。欠番・試験番号も番号を再利用しない。
LAST_PRESENTER_ID = 0          # 0=Excelの最大IDを自動取得。固定時は実際の最終回答ID。
FORM_EXPORT_TIMEZONE = "Asia/Tokyo"  # Excelの「完了時刻」のタイムゾーン。要確認。

# 事務局で確定済みの番号を指定。整数と4桁文字列の両方が使える。
MULTIPLE_APPLICATION_REJECT_IDS = []   # 多重申込：Rejectし、受付番号をWeb公開。
COAUTHOR_GALLERY_MOVE_IDS = []        # 共著重複：ブース対象外、ギャラリー候補。
TEST_REGISTRATION_REJECT_IDS = []      # 試験登録：完全除外。受付番号は非公開。

BOOTH_CAPACITY = 36         # A/B/Cそれぞれ最大36件
POSTER_CAPACITY = 8         # A/B/Cそれぞれ最大8件（3/28、計24件）
ONSITE_CAPACITY = 28        # 3/27、主発表者1人1席（居室・委員は定員外）
DRAW_DATE = "2027-02-01"
DEADLINE_JST = "2027-02-01 12:00:00"
CLOSE_READY_HOUR_JST = 16  # 時刻は安全側の目安。終値のデータ公開時刻は保証しない。
PUBLIC_INCLUDE_TITLES = False  # Trueにするのは公開許諾を別途確認した場合だけ。
# ===========================================================================

import argparse
import csv
import hashlib
import html
import json
import re
import shutil
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

SLOTS = ("A", "B", "C")
JST = ZoneInfo("Asia/Tokyo")
# Microsoft Formsは質問文をExcelの列名に使用する。文面が変更された場合にも
# 部分一致で吸収するが、曖昧なら誤処理せず停止し、列名を画面に表示する。
FIELD_PATTERNS = {
    "id": ("ID", "回答ID", "回答番号", "response id", "respondent id"),
    "completed": ("完了時刻", "完了日時", "completion time", "submit time", "終了時刻"),
    "name": ("主発表者の氏名",),
    "email": ("主発表者のメールアドレス",),
    "action": ("手続きの種類",),
    "old_modify": ("以前の受付番号(申込修正", "修正前の受付番号"),
    "old_cancel": ("以前の受付番号(申込取消", "取消する発表の受付番号"),
    "slot": ("発表するコアタイム",),
    "title": ("発表題目",),
    "summary": ("発表概要",),
    "affiliation": ("主発表者の所属",),
    "coauthors": ("共同発表者の氏名",),
    "consent": ("発表者全員から同意を得て",),
    "anti": ("アンチハラスメントポリシーを確認した",),
    "privacy": ("個人情報保護ポリシーを確認した",),
    "onsite": ("現地配信・参加を希望する", "現地配信を希望する"),
    "poster": ("現地ポスター発表を希望する",),
    "gallery": ("フェス・ギャラリーへの資料掲載を希望する",),
    "online": ("オンライン参加を希望する",),
    "organizer": ("次回以降の言語学フェスの運営に参加したい",),
    "upload": ("発表資料をアップロード", "発表資料のアップロード"),
}
REQUIRED_FIELDS = ("id", "completed", "name", "email", "action", "slot", "title", "coauthors", "onsite", "poster", "gallery")


def norm(value: object) -> str:
    """日本語質問の空白・全半角の揺れを吸収。日付・値は加工しない。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).casefold())


def fmt_id(value: object) -> str:
    """Microsoft Formsの回答IDを、全枠共通の0001形式に変換。"""
    v = str(value or "").strip()
    if isinstance(value, int):
        v = str(value)
    if isinstance(value, float) and value.is_integer():
        v = str(int(value))  # Excelが整数IDを 12.0 として返す場合にも対応
    if not re.fullmatch(r"[0-9]{1,4}", v) or not (1 <= int(v) <= 9999):
        raise ValueError(f"回答IDは1〜9999の整数である必要があります: {value!r}")
    return f"{int(v):04d}"


def clean_email(value: object) -> str:
    v = str(value or "").strip().casefold()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", v):
        raise ValueError(f"メールアドレスの形式を確認してください: {value!r}")
    return v


def canon_author(raw: str) -> str:
    """同一枠共著者重複の判定キー。所属の括弧書きは取り除く。"""
    # PDFのQ9は「氏名（所属）;氏名（所属）」なので、所属が変わっていても
    # 同じ著者を検出できるよう末尾の括弧を取り除く。
    s = re.sub(r"\s*[(（][^()（）]*[)）]\s*$", "", str(raw).strip())
    return norm(s)


def split_author_names(primary: str, coauthor_text: str) -> set[str]:
    values = [primary] + [x for x in re.split(r"[;；]", coauthor_text or "") if x.strip()]
    names = {canon_author(x) for x in values}
    if not names or "" in names:
        raise ValueError("空の著者名があります")
    return names


def is_yes(value: object) -> bool:
    s = norm(value)
    return s.startswith("はい") or s in ("yes", "true", "1")


def procedure(value: object) -> str:
    s = norm(value)
    if "取消" in s or "キャンセル" in s: return "CANCEL"
    if "修正" in s or "上書き" in s: return "UPDATE"
    if "新規" in s: return "NEW"
    raise ValueError(f"手続きの種類が読み取れません: {value!r}")


def onsite_choice(value: object) -> str:
    """Q13の3択。'はい'だけでなく国語研内・委員の扱いを保持する。"""
    s = norm(value)
    if s.startswith("いいえ") or s in ("no", "false", "0"):
        return "NO"
    if not s.startswith("はい"):
        raise ValueError(f"現地配信の回答が読み取れません: {value!r}")
    # Q13: 「はい（国語研内に居室がある or 運営委員である）」を定員外に。
    # 「居室がない and 運営委員でない」は定員内。単純な「居室」部分一致は危険。
    if "居室がある" in s or "運営委員である" in s or "実行委員である" in s:
        return "OUTSIDE_CAPACITY"
    if "居室がない" in s or "運営委員でない" in s or "実行委員でない" in s:
        return "SEAT_REQUEST"
    raise ValueError(f"現地配信の3択が判別できません。正規化列を確認: {value!r}")


def parse_time(value: object, timezone: str = FORM_EXPORT_TIMEZONE) -> datetime:
    """Forms Excelの時刻はタイムゾーンが明示されない場合がある。必ず設定で指定。"""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        s = str(value or "").strip()
        if not s:
            raise ValueError("完了時刻が空です。締切判定ができません")
        s = s.replace("年", "-").replace("月", "-").replace("日", " ").replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            parsed = None
            for fmt in ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
                try:
                    parsed = datetime.strptime(s, fmt)
                    break
                except ValueError:
                    continue
            if parsed is None:
                raise ValueError(f"完了時刻の形式に対応していません: {value!r}")
            dt = parsed
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(timezone))
    return dt.astimezone(JST)


def match_columns(columns: list[str]) -> dict[str, str | None]:
    """Microsoft Forms Excelの実際の質問タイトルから列を選ぶ。"""
    result: dict[str, str | None] = {}
    for field, patterns in FIELD_PATTERNS.items():
        candidates = [c for c in columns if any(
            (norm(c) == norm(p)) if field == "id" else (norm(p) in norm(c))
            for p in patterns)]
        if len(candidates) > 1:
            # 長文の「発表者全員が...」で誤った列に重複一致すると危険。
            raise ValueError(f"列 {field} が複数あります。質問名を整理してください: {candidates}")
        result[field] = candidates[0] if candidates else None
    missing = [f for f in REQUIRED_FIELDS if result[f] is None]
    if missing:
        raise ValueError(f"Microsoft Forms出力の列が見つかりません: {missing}\n実際の列名: {columns}")
    return result


def read_forms_export(path: Path, timezone: str = FORM_EXPORT_TIMEZONE) -> list[dict]:
    """Microsoft Formsの回答を「一行一回答」に保って読む。欠番は補わない。"""
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        try:
            import openpyxl
        except ImportError as ex:
            raise RuntimeError("Excelを読むために pip install openpyxl が必要です") from ex
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            ws = wb.active
            data = ws.iter_rows(values_only=True)
            columns = [str(x or "").strip() for x in next(data)]
            source = (dict(zip(columns, values)) for values in data)
            records = _parse_rows(source, columns, timezone)
        finally:
            wb.close()
        return records
    if suffix == ".csv":
        # ExcelでCSVへ変換するときは文字コードUTF-8を使う。
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            return _parse_rows(reader, reader.fieldnames or [], timezone)
    raise ValueError("入力ファイルはMicrosoft Forms回答の .xlsx または .csv にしてください")


def _parse_rows(source, columns: list[str], timezone: str) -> list[dict]:
    fields = match_columns(columns)
    records = []
    for row_number, row in enumerate(source, 2):
        if not any(str(x or "").strip() for x in row.values()):
            continue
        try:
            val = {field: row.get(column, "") if column else "" for field, column in fields.items()}
            aid = fmt_id(val["id"])
            act = procedure(val["action"])
            d = {
                "id": aid, "no": int(aid), "completed": parse_time(val["completed"], timezone),
                "name": str(val["name"] or "").strip(),
                "email": clean_email(val["email"]), "action": act,
                "old_id": "", "slot": "", "title": "", "summary": "",
                "affiliation": "", "coauthors": "", "author_keys": set(),
                "poster_requested": False, "gallery_allowed": False, "onsite": "NO",
                "online_requested": False, "future_organizer": False,
                "upload_reference": "", "status": "UNPROCESSED", "reason": "",
                "booth_rank": "", "booth_hash": "", "booth_result": "",
                "poster_rank": "", "poster_hash": "", "poster_result": "",
                "onsite_result": "",
            }
            if not d["name"]:
                raise ValueError("氏名が空です")
            if act in ("UPDATE", "CANCEL"):
                old = val["old_modify"] if act == "UPDATE" else val["old_cancel"]
                if old is None or not str(old).strip():
                    raise ValueError("修正・取消には以前の受付番号が必要です")
                d["old_id"] = fmt_id(old)
            if act != "CANCEL":
                slot = norm(val["slot"]).upper()
                if slot not in SLOTS:
                    # Microsoft Formsの選択肢例「A 未完成研究...」から冒頭1文字を取る。
                    slot = str(val["slot"] or "").strip().upper()[:1]
                if slot not in SLOTS:
                    raise ValueError(f"コアタイムはA/B/Cにしてください: {val['slot']!r}")
                d["slot"] = slot
                d["title"] = str(val["title"] or "").strip()
                d["summary"] = str(val["summary"] or "").strip()
                d["affiliation"] = str(val["affiliation"] or "").strip()
                d["coauthors"] = str(val["coauthors"] or "").strip()
                d["author_keys"] = split_author_names(d["name"], d["coauthors"])
                d["poster_requested"] = is_yes(val["poster"])
                d["gallery_allowed"] = is_yes(val["gallery"])
                d["onsite"] = onsite_choice(val["onsite"])
                d["online_requested"] = is_yes(val["online"])
                d["future_organizer"] = is_yes(val["organizer"])
                d["upload_reference"] = str(val["upload"] or "")
                if not d["title"]:
                    raise ValueError("発表題目が空です")
                # 同意事項はFormsの必須回答で保証されるが、念のため再検査する。
                for req in ("consent", "anti", "privacy"):
                    if fields[req] is not None and not is_yes(val[req]):
                        raise ValueError(f"同意事項 {req} が『はい』ではありません")
            records.append(d)
        except ValueError as exc:
            raise ValueError(f"Excel/CSV {row_number} 行目: {exc}") from exc
    if not records:
        raise ValueError("Excelに申込回答がありません")
    seen = set()
    for r in records:
        if r["id"] in seen:
            raise ValueError(f"フォーム回答IDが重複しています: {r['id']}")
        seen.add(r["id"])
    return sorted(records, key=lambda r: r["no"])


def manual_sets(records: list[dict], last_id: int) -> dict[str, set[str]]:
    """手動番号リストを検査。誤指定・重複は無言で無視せず停止。"""
    sources = {
        "multiple": MULTIPLE_APPLICATION_REJECT_IDS,
        "coauthor": COAUTHOR_GALLERY_MOVE_IDS,
        "test": TEST_REGISTRATION_REJECT_IDS,
    }
    ids = {r["id"] for r in records}
    result = {}
    used = {}
    for key, raw in sources.items():
        group = set()
        for value in raw:
            aid = fmt_id(value)
            if aid not in ids or int(aid) > last_id:
                raise ValueError(f"{key}に存在しない／最後の受付を超えるIDがあります: {aid}")
            if aid in used or aid in group:
                raise ValueError(f"手動リストに重複したIDがあります: {aid}")
            group.add(aid)
            used[aid] = key
        result[key] = group
    return result


def classify_submissions(records: list[dict]) -> dict:
    """まず履歴を確定。共著者重複は履歴修正・取消の処理後に判定する。"""
    if not 1 <= MAX_APPLICATION_NUMBER <= 9999:
        raise ValueError("MAX_APPLICATION_NUMBERは1〜9999にしてください")
    max_seen = max(r["no"] for r in records)
    if max_seen > MAX_APPLICATION_NUMBER:
        raise ValueError(f"最大ID={max_seen}はMAX_APPLICATION_NUMBERを超えます")
    if LAST_PRESENTER_ID and max_seen != LAST_PRESENTER_ID:
        raise ValueError(f"フォーム出力の最大回答ID {max_seen} と LAST_PRESENTER_ID {LAST_PRESENTER_ID} が一致しません")
    last = LAST_PRESENTER_ID or max_seen
    groups = manual_sets(records, last)
    by_id = {r["id"]: r for r in records}
    cutoff = datetime.fromisoformat(DEADLINE_JST).replace(tzinfo=JST)
    # Microsoft Formsの回答IDが本当に受付順で増加しているかを、完了時刻で照合。
    # 反対順があれば「最後の応募」を誤判定する危険があるため本番処理を止める。
    for previous, current in zip(records, records[1:]):
        if current["completed"] < previous["completed"]:
            raise ValueError(
                f"回答IDと完了時刻の順序が逆転しています: {previous['id']}→{current['id']}。"
                "Formsの回答IDの付与順序を事務局で確認してください"
            )
    for r in records:
        aid = r["id"]
        if aid in groups["test"]:
            r.update(status="REJECT_TEST", reason="試験登録。公開しない")
            continue
        if aid in groups["multiple"]:
            r.update(status="REJECT_MULTIPLE", reason="事務局による多重申込Reject")
            continue
        if r["completed"] >= cutoff:
            r.update(status="REJECT_LATE", reason="日本時間2027-02-01 12:00の締切後")
            continue
        if r["action"] == "NEW":
            r.update(status="ACTIVE", reason="新規")
            continue
        # 修正・取消の承認は、回答IDと申込メール・氏名の両方を照合する。
        old = by_id.get(r["old_id"])
        if not old or old["no"] >= r["no"]:
            raise ValueError(f"{aid}: 以前の受付番号 {r['old_id']} が見つからない／番号順が不正")
        if old["status"] != "ACTIVE":
            raise ValueError(f"{aid}: 以前の受付番号 {r['old_id']} は現在有効ではありません ({old['status']})。確認してください")
        if old["email"] != r["email"] or norm(old["name"]) != norm(r["name"]):
            raise ValueError(f"{aid}: 旧番号 {r['old_id']} と氏名・メールアドレスが一致しません。手動照合が必要です")
        if r["action"] == "UPDATE":
            old.update(status="SUPERSEDED", reason=f"修正回答{aid}に置換。ギャラリー対象外")
            r.update(status="ACTIVE", reason=f"修正・旧番号{r['old_id']}")
        elif r["action"] == "CANCEL":
            old.update(status="CANCELLED", reason=f"取消回答{aid}を照合済。ギャラリー対象外")
            r.update(status="CANCEL_REQUEST", reason=f"旧番号{r['old_id']}を取消")
        else:
            raise AssertionError(r["action"])
    # ACTIVE以外の回答（試験、Reject、履歴取消）は著者重複判定の対象外。
    latest = {}
    for r in records:
        if r["status"] == "ACTIVE":
            for key in r["author_keys"]:
                latest[(r["slot"], key)] = r["id"]
    for r in records:
        if r["status"] != "ACTIVE":
            continue
        later = sorted({latest[(r["slot"], author)] for author in r["author_keys"]
                        if latest[(r["slot"], author)] != r["id"]})
        if later:
            r.update(status="GALLERY_COAUTHOR", reason="同じ枠で共著者重複。後の申込="+",".join(later))
        elif r["id"] in groups["coauthor"]:
            r.update(status="GALLERY_MANUAL", reason="事務局指定の共著重複ギャラリー移動")
    for aid in groups["coauthor"]:
        if by_id[aid]["status"] not in ("GALLERY_COAUTHOR", "GALLERY_MANUAL"):
            raise ValueError(f"共著ギャラリー指定ID {aid} は修正・取消・Reject等です。手動リストを確認してください")
    return {"last_id": last, "latest_by_slot_author": latest,
            "manual_lists": {k: sorted(v) for k, v in groups.items()}}


def hash_item(parts: list[str]) -> tuple[str, str]:
    text = "|".join(parts)
    return text, hashlib.sha256(text.encode("utf-8")).hexdigest()


def price_string(value: object) -> str:
    """終値はカンマなし小数2桁で固定。float誤差をDecimalで丸める。"""
    try:
        raw = Decimal(str(value).replace(",", ""))
        if not raw.is_finite() or raw <= 0:
            raise ValueError("日経平均終値は正の有限数にしてください")
        return str(raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise ValueError(f"終値の形式が不正です: {value!r}") from exc


def obtain_nikkei_close(mode: str, now: datetime | None = None,
                        override: str | None = None) -> tuple[str, str, str]:
    """既知の終値で『本番』にならないよう、日付と時刻を検査する。"""
    now = (now or datetime.now(JST)).astimezone(JST)
    final_ready = datetime.fromisoformat(DRAW_DATE+"T16:00:00").replace(tzinfo=JST)
    if mode not in ("auto", "preview", "final"):
        raise ValueError("MODEはauto/preview/finalのいずれかです")
    phase = "FINAL" if mode == "final" or (mode == "auto" and now >= final_ready) else "PREVIEW"
    if phase == "FINAL" and now < final_ready:
        raise ValueError("本番用の終値は2027-02-01 16:00 JSTより前には使用できません")
    if override:
        # 手入力は検算用。自動での本番認定には使わず、PREVIEW表示を維持。
        if phase == "FINAL":
            raise ValueError("手入力終値で本番扱いにはできません。自動取得値を公式値と照合してください")
        return "手入力（予行演習）", price_string(override), "PREVIEW"
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("株価取得には pip install yfinance が必要です") from exc
    start = (now.date() - timedelta(days=24)).isoformat()
    end = (now.date() + timedelta(days=2)).isoformat()
    if phase == "FINAL":
        start = (date.fromisoformat(DRAW_DATE)-timedelta(days=5)).isoformat()
        end = (date.fromisoformat(DRAW_DATE)+timedelta(days=2)).isoformat()
    df = yf.download("^N225", start=start, end=end, interval="1d",
                     progress=False, auto_adjust=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError("Yahoo Financeの日経平均(^N225)を取得できませんでした")
    close_col = df["Close"]
    # yfinanceの版によってClose列がDataFrame（MultiIndex）になる。
    if hasattr(close_col, "columns"):
        close_col = close_col.iloc[:, 0]
    prices = []
    for idx, val in close_col.dropna().items():
        d = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
        if phase == "FINAL":
            if d == date.fromisoformat(DRAW_DATE):
                prices.append((d.isoformat(), price_string(val)))
        elif d <= now.date() and not (d == now.date() and now.hour < CLOSE_READY_HOUR_JST):
            prices.append((d.isoformat(), price_string(val)))
    if not prices:
        raise RuntimeError((f"指定日{DRAW_DATE}の終値が配信されていません。本番を中止します"
                            if phase == "FINAL" else "利用可能な確定終値がまだありません"))
    d, p = max(prices)
    return d, p, phase


def assign_booths(records: list[dict], price: str) -> dict[str, list[dict]]:
    """抽選対象のみを各枠でSHA-256昇順。辞退があっても繰上げはしない。"""
    groups = {}
    for slot in SLOTS:
        candidates = [r for r in records if r["status"] == "ACTIVE" and r["slot"] == slot]
        for r in candidates:
            r["booth_input"], r["booth_hash"] = hash_item(["lingfes2027", slot, price, r["id"]])
        candidates.sort(key=lambda r: (r["booth_hash"], r["id"]))
        for rank, r in enumerate(candidates, 1):
            r["booth_rank"] = rank
            if rank <= BOOTH_CAPACITY:
                r["status"] = "BOOTH_SELECTED"
                r["booth_result"] = "ブース採択"
            else:
                r["status"] = "GALLERY_OVERFLOW"
                r["booth_result"] = "定員超過・ギャラリー対象（繰上げなし）"
        groups[slot] = candidates
    return groups


def assign_posters(records: list[dict], price: str) -> dict[str, list[dict]]:
    """現地ポスターはブース採択者のみ。A/B/C各8件、主発表者が参加。"""
    groups = {}
    for slot in SLOTS:
        candidates = [r for r in records if r["status"] == "BOOTH_SELECTED"
                      and r["slot"] == slot and r["poster_requested"]]
        for r in candidates:
            r["poster_input"], r["poster_hash"] = hash_item(
                ["lingfes2027", "POSTER", slot, price, r["id"]])
        candidates.sort(key=lambda r: (r["poster_hash"], r["id"]))
        for rank, r in enumerate(candidates, 1):
            r["poster_rank"] = rank
            r["poster_result"] = "現地ポスター採択" if rank <= POSTER_CAPACITY else "現地ポスター非採択"
        groups[slot] = candidates
    return groups


def assign_onsite(records: list[dict], price: str) -> dict:
    """3/27国語研所内配信はオンラインブース採択者の希望者だけを対象とし、主発表者1人1席。"""
    allowed = {"BOOTH_SELECTED"}  # 所内配信はオンラインブース採択者のみ。ギャラリー対象者は除外。
    people = defaultdict(list)
    for r in records:
        if r["status"] in allowed:
            people[(r["email"], norm(r["name"]))].append(r)
    person_rows = []
    for (_email, _name), applications in people.items():
        apps = sorted(applications, key=lambda r: r["no"])
        person_id = apps[0]["id"]  # 同じ主発表者がA/Cに応募しても抽選権を増やさない。
        opts = {r["onsite"] for r in apps}
        if "OUTSIDE_CAPACITY" in opts and "SEAT_REQUEST" in opts:
            raise ValueError(f"申込{[r['id'] for r in apps]}の現地居室・委員の回答が矛盾しています。事務局で確認してください")
        if opts == {"NO"}:
            status = "希望なし"
        elif "OUTSIDE_CAPACITY" in opts:
            status = "28席の定員外（居室あり・実行委員）"
        else:
            status = "28席抽選対象"
        priority = any(r["poster_result"] == "現地ポスター採択" for r in apps)
        literal, digest = hash_item(["lingfes2027", "ONSITE", price, person_id])
        person_rows.append({"person_id":person_id, "name":apps[0]["name"],
                            "email":apps[0]["email"], "applications": ";".join(r["id"] for r in apps),
                            "priority_poster":priority, "status":status,
                            "hash_input":literal, "sha256":digest, "rank":""})
    # ポスター当選による優先採択は、Q13で現地配信・参加を希望した人だけ。
    waiting = [p for p in person_rows if p["status"] == "28席抽選対象"]
    waiting.sort(key=lambda p: (not p["priority_poster"], p["sha256"], p["person_id"]))
    for rank, p in enumerate(waiting, 1):
        p["rank"] = rank
        if rank <= ONSITE_CAPACITY:
            p["status"] = ("現地配信・参加採択（ポスター優先）" if p["priority_poster"]
                           else "現地配信・参加採択（一般抽選）")
        else:
            p["status"] = "現地配信・参加非採択（繰上げなし）"
    status_by_person = {(p["email"], norm(p["name"])):p["status"] for p in person_rows}
    for r in records:
        if r["status"] in allowed:
            r["onsite_result"] = status_by_person[(r["email"], norm(r["name"]))]
    return {"people": sorted(person_rows, key=lambda p: p["person_id"]),
            "ranked": waiting,
            "selected": [p for p in waiting if p["rank"] <= ONSITE_CAPACITY],
            "outside": [p for p in person_rows if p["status"].startswith("28席の定員外")]}


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Excelの数式注入対策：氏名・題目などの文字列をCSVへ出す際にサニタイズ。
            out = {}
            for field in headers:
                v = row.get(field, "")
                if isinstance(v, set): v = ";".join(sorted(v))
                if isinstance(v, datetime): v = v.isoformat()
                if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")):
                    v = "'" + v
                out[field] = v
            writer.writerow(out)


def public_html(records: list[dict], booth: dict, poster: dict, onsite: dict,
                price_date: str, price: str, phase: str) -> str:
    """外部CSS/JS不要の静的HTML。氏名・メールアドレス・同意していない題目は出さない。"""
    def e(x): return html.escape(str(x), quote=True)
    def tbl(rows, cols):
        if not rows: return "<p>該当なし</p>"
        head = "".join(f"<th>{e(label)}</th>" for _,label in cols)
        body = "".join("<tr>"+"".join(f"<td>{e(r.get(k,''))}</td>" for k,_ in cols)+"</tr>" for r in rows)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
    booth_rows = [{"id":r["id"], "slot":r["slot"], "rank":r["booth_rank"],
                   "result":r["booth_result"]} for slot in SLOTS for r in booth[slot]]
    poster_rows = [{"id":r["id"], "slot":r["slot"], "rank":r["poster_rank"],
                    "result":r["poster_result"]} for slot in SLOTS for r in poster[slot]]
    onsite_rows = [{"id":p["person_id"], "rank":p["rank"],
                    "priority":"あり" if p["priority_poster"] else "なし",
                    "result":p["status"]} for p in onsite["ranked"]]
    rejected = [{"id":r["id"], "slot":r["slot"]} for r in records if r["status"]=="REJECT_MULTIPLE"]
    gallery = [{"id":r["id"], "slot":r["slot"],
                "consent":"資料掲載希望あり" if r["gallery_allowed"] else "資料掲載希望なし"}
               for r in records if r["status"] in ("GALLERY_COAUTHOR","GALLERY_MANUAL","GALLERY_OVERFLOW")]
    robots = '<meta name="robots" content="noindex,nofollow">' if phase!="FINAL" else ""
    notice = ("【予行演習：公開禁止】実際の抽選結果ではありません。" if phase!="FINAL"
              else "【本番結果候補】日経公式終値・回答原簿を事務局が検証したうえで公開してください。")
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8">{robots}
<meta name="viewport" content="width=device-width,initial-scale=1"><title>言語学フェス2027 公開抽選結果</title>
<style>body{{font-family:system-ui,'Noto Sans JP',sans-serif;line-height:1.65;color:#222;margin:24px auto;max-width:1050px;padding:0 18px}}
h1,h2{{color:#172e56}}h2{{margin-top:36px;border-bottom:1px solid #aab5c2;padding-bottom:6px}}.notice{{border:2px solid #c70;padding:10px}}table{{border-collapse:collapse;width:100%;font-size:.91rem}}th,td{{border-bottom:1px solid #ccd4dc;padding:6px;text-align:left}}th{{background:#eaf0f7}}code{{word-break:break-all}}</style></head>
<body><h1>言語学フェス2027 公開抽選結果</h1><p class="notice">{e(notice)}</p>
<p>抽選日：2027年2月1日（月）。使用終値：{e(price_date)} / {e(price)} 円。SHA-256（UTF-8）の16進数昇順。</p>
<p>ブース：A/B/C各36件。ポスター：A/B/C各8件。現地配信・参加：28席（居室あり・実行委員は定員外）。繰上げ採択は行いません。</p>
<h2>3月27日 オンラインブース抽選</h2>{tbl(booth_rows, [('id','申込番号'),('slot','枠'),('rank','順位'),('result','区分')])}
<h2>3月28日 現地ポスター抽選</h2>{tbl(poster_rows, [('id','申込番号'),('slot','枠'),('rank','順位'),('result','区分')])}
<h2>3月27日 現地配信・参加（28席）</h2><p>申込番号は同一の主発表者について最小の有効番号で表示。所内配信希望の現地ポスター採択者を先に割当て、残る28席をオンラインブース採択者の所内配信希望者から抽選。ギャラリー対象者と一般参加のみの方は対象外。</p>
{tbl(onsite_rows, [('id','代表申込番号'),('rank','優先枠込み順位'),('priority','ポスター優先'),('result','区分')])}
<h2>多重申込Reject一覧</h2>{tbl(rejected,[('id','申込番号'),('slot','枠')])}
<h2>フェス・ギャラリー対象一覧</h2><p>資料を掲載するのは掲載希望を得た申込のみです。共著重複・定員超過の申込はブースの繰上げ対象にはなりません。</p>
{tbl(gallery,[('id','申込番号'),('slot','枠'),('consent','公開希望')])}
<p>試験登録・修正履歴・取消・個人情報は掲載しません。</p></body></html>'''


def run_draw(source_file: Path, outdir: Path, mode: str = MODE,
             manual_price: str | None = None, now: datetime | None = None) -> dict:
    """同じ入力原簿と株価から、何度でも完全に再現可能な抽選結果を生成する。"""
    records = read_forms_export(source_file, FORM_EXPORT_TIMEZONE)
    history = classify_submissions(records)
    price_date, price, phase = obtain_nikkei_close(mode, now=now, override=manual_price)
    booths = assign_booths(records, price)
    posters = assign_posters(records, price)
    onsite = assign_onsite(records, price)
    outdir.mkdir(parents=True, exist_ok=True)
    internal = outdir / "internal_private"
    internal.mkdir(exist_ok=True)
    cols = ("id", "action", "old_id", "completed", "status", "reason", "slot", "name", "email",
            "affiliation", "coauthors", "title", "summary", "upload_reference", "gallery_allowed",
            "poster_requested", "onsite", "onsite_result", "booth_rank", "booth_result", "booth_hash",
            "poster_rank", "poster_result", "poster_hash", "future_organizer")
    write_csv(internal / "全受付履歴_内部用.csv", list(cols), records)
    write_csv(internal / "ブース抽選_内部用.csv",
              ["id", "slot", "name", "email", "title", "booth_rank", "booth_hash", "booth_result"],
              [r for s in SLOTS for r in booths[s]])
    write_csv(internal / "現地ポスター抽選_内部用.csv",
              ["id", "slot", "name", "email", "title", "poster_rank", "poster_hash", "poster_result"],
              [r for s in SLOTS for r in posters[s]])
    write_csv(internal / "現地配信抽選_内部用.csv",
              ["person_id", "applications", "name", "email", "priority_poster", "rank", "status", "sha256"],
              onsite["people"])
    write_csv(internal / "共著者別_最後の発表者ID_内部用.csv",
              ["slot", "author_key", "last_id"],
              [{"slot":s,"author_key":a,"last_id":i} for (s,a),i in sorted(history["latest_by_slot_author"].items())])
    write_csv(internal / "運営参加希望者_内部用.csv", ["id","name","email","slot"],
              [r for r in records if r["status"] in ("BOOTH_SELECTED","GALLERY_OVERFLOW","GALLERY_COAUTHOR","GALLERY_MANUAL") and r["future_organizer"]])
    for label, statuses in (
        ("多重申込Reject_内部用.csv", {"REJECT_MULTIPLE"}),
        ("試験登録Reject_内部用.csv", {"REJECT_TEST"}),
        ("申込修正取消_内部用.csv", {"SUPERSEDED","CANCELLED","CANCEL_REQUEST"}),
        ("共著申込ギャラリー移動_内部用.csv", {"GALLERY_COAUTHOR","GALLERY_MANUAL"}),
        ("定員超過_ギャラリー対象_内部用.csv", {"GALLERY_OVERFLOW"}),
        ("締切後_内部用.csv", {"REJECT_LATE"}),
    ):
        write_csv(internal / label, ["id","slot","status","reason","gallery_allowed","title","email"],
                  [r for r in records if r["status"] in statuses])
    public = outdir / "web_public"
    # 古い公開結果ファイルが残ると、意図せず過去の内容を公開する危険がある。
    # このフォルダにはプログラム生成物以外は置かないという約束で毎回初期化。
    if public.exists():
        shutil.rmtree(public)
    public.mkdir(exist_ok=True)
    write_csv(public / "ブース抽選順位_匿名.csv",
              ["id","slot","booth_rank","booth_hash","booth_result"],
              [r for s in SLOTS for r in booths[s]])
    write_csv(public / "現地ポスター抽選順位_匿名.csv",
              ["id","slot","poster_rank","poster_hash","poster_result"],
              [r for s in SLOTS for r in posters[s]])
    write_csv(public / "現地配信抽選順位_匿名.csv",
              ["person_id","rank","priority_poster","status","sha256"], onsite["ranked"])
    write_csv(public / "多重申込Reject一覧.csv", ["id", "slot", "status"],
              [r for r in records if r["status"]=="REJECT_MULTIPLE"])
    write_csv(public / "ギャラリー対象_匿名.csv", ["id","slot","status","gallery_allowed"],
              [r for r in records if r["status"] in ("GALLERY_COAUTHOR","GALLERY_MANUAL","GALLERY_OVERFLOW")])
    (public / "index.html").write_text(public_html(records,booths,posters,onsite,price_date,price,phase),encoding="utf-8")
    meta = {
        "draw_date":DRAW_DATE,"deadline_jst":DEADLINE_JST,"price_date":price_date,
        "nikkei_close":price,"phase":phase,"price_source":"Yahoo Finance ^N225, verify with Nikkei official",
        "hash_order":"SHA-256 hex ascending","four_digit_padding":True,
        "hash_patterns":["lingfes2027|{slot}|{close}|{id4}",
                         "lingfes2027|POSTER|{slot}|{close}|{id4}",
                         "lingfes2027|ONSITE|{close}|{min_active_id4_per_person}"],
        "booth_capacity_per_slot":BOOTH_CAPACITY,"poster_capacity_per_slot":POSTER_CAPACITY,
        "onsite_seats":ONSITE_CAPACITY,"onsite_population":"primary presenters with accepted online booths and onsite requests; excludes gallery and participation-only",
        "no_waitlist":True,
        "counts":{"booths":{s:sum(r["booth_result"]=="ブース採択" for r in booths[s]) for s in SLOTS},
                  "posters":{s:sum(r["poster_result"]=="現地ポスター採択" for r in posters[s]) for s in SLOTS},
                  "onsite_selected":len(onsite["selected"]),"onsite_outside":len(onsite["outside"]),
                  "multiple_rejected":sum(r["status"]=="REJECT_MULTIPLE" for r in records)},
    }
    (public / "抽選条件_公開用.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    # 公開用ディレクトリに内部のメールや氏名が混ざっていないか機械的に確認。
    for p in public.iterdir():
        if p.suffix not in (".html", ".csv", ".json"):
            raise RuntimeError(f"Web公開フォルダに予期しないファイル: {p.name}")
    report = dict(meta)
    report.update({"input_sha256":hashlib.sha256(source_file.read_bytes()).hexdigest(),
                   "last_form_response_id":history["last_id"],
                   "manual_lists":history["manual_lists"],
                   "timestamp_timezone_assumption":FORM_EXPORT_TIMEZONE})
    (internal / "実行条件_監査用.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main():
    parser=argparse.ArgumentParser(description="言語学フェス2027：FormsのExcelからブース・ポスター・現地配信抽選")
    parser.add_argument("--input",default=INPUT_FILE,help="Microsoft Formsの回答.xlsx/.csv")
    parser.add_argument("--output",default=OUTPUT_DIR,help="結果出力先。GitHubへコミット禁止")
    parser.add_argument("--mode",choices=["auto","preview","final"],default=MODE)
    parser.add_argument("--preview-close",default=None,help="予行演習の架空終値（本番には使用不可）")
    args=parser.parse_args()
    path=args.input
    if not path:
        try:
            from google.colab import files
            print("Microsoft Formsの回答Excel(.xlsx)をアップロードしてください。")
            uploaded=files.upload()
            if len(uploaded)!=1: raise ValueError("1個のExcel/CSVだけをアップロードしてください")
            path=next(iter(uploaded))
        except ImportError as ex:
            raise SystemExit("Mac/Windowsでは --input 回答.xlsx を指定してください") from ex
    report=run_draw(Path(path),Path(args.output),args.mode,args.preview_close)
    print("抽選実行結果（個人情報は表示しません）:")
    print(json.dumps({k:report[k] for k in ("draw_date","price_date","nikkei_close","phase","counts")},ensure_ascii=False,indent=2))
    print("出力先:",Path(args.output).resolve())
    print("[重要] internal_private/ と入力ExcelはGitHubへアップロードしないでください")
    if report["phase"] != "FINAL": print("[重要] PREVIEWは公開禁止です")
    try:
        from google.colab import files
    except ImportError:
        pass
    else:
        # 応募者の氏名やメールアドレスを含むので、このZIPは個人用にだけ保存。
        archive=shutil.make_archive(str(Path(args.output)),"zip",root_dir=Path(args.output))
        files.download(archive)


if __name__=="__main__":
    main()
