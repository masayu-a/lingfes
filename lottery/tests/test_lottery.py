"""株価ネット接続なしで動く、Forms入力／三段抽選／公開安全性のテスト。"""
import csv
import hashlib
import importlib.util
import json
import pathlib
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lingfes2027_lottery", ROOT / "lingfes2027_lottery.py")
lottery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lottery)

HEADERS = [
    "ID", "開始時刻", "完了時刻", "名前", "電子メール",
    "1. 主発表者の氏名", "2. 主発表者のメールアドレス",
    "3. 手続きの種類", "4. 以前の受付番号（申込修正の場合のみ）",
    "5. 発表するコアタイム", "6. 発表題目", "7. 発表概要（200字程度）",
    "8. 主発表者の所属", "9. 共同発表者の氏名（所属）；区切り",
    "10. 発表者全員から同意を得て、発表数の制限と参加申込が別であることを確認した",
    "11. 発表者全員がアンチハラスメントポリシーを確認した",
    "12. 発表者全員が国立国語研究所個人情報保護ポリシーを確認した",
    "13. １日目（3月27日）の国語研からの現地配信・参加を希望する",
    "14. ２日目（3月28日）の現地ポスター発表を希望する",
    "15. １日目のブース発表の抽選に漏れた場合に、フェス・ギャラリーへの資料掲載を希望する",
    "16. １日目のブース発表の抽選に漏れた場合、3月27日のオンライン参加を希望する",
    "17. 次回以降の言語学フェスの運営に参加したい。",
    "18. 発表資料をアップロードしてください (100MB)",
    "19. 以前の受付番号（申込取消の場合のみ）"
]
ONSITE_YES = "はい（国語研内の居室がない and 運営委員でない：【抽選により決定】）"
ONSITE_OUT = "はい（国語研内に居室がある or 運営委員である）"


def form_row(n, slot="A", name=None, coauthors="", action="新規申込", old="", onsite=ONSITE_YES,
             poster="はい", gallery="はい", date="2027-01-31 16:00:00", email=None):
    name = name or f"架空発表者{n}"
    email = email or f"person{n}@example.org"
    values = [n, "2027-01-31 15:00:00", date, "", "", name, email, action,
              old if "修正" in action else "", f"{slot} 試験用", f"発表題目{n}",
              "テスト概要", "架空大学", coauthors, "はい", "はい", "はい",
              onsite, poster, gallery, "はい", "いいえ", "test.pdf",
              old if "取消" in action else ""]
    return dict(zip(HEADERS, values))


def write_test_xlsx(path, rows):
    import openpyxl
    book=openpyxl.Workbook(); sheet=book.active
    sheet.append(HEADERS)
    for row in rows: sheet.append([row.get(x, "") for x in HEADERS])
    book.save(path)


class LotteryTests(unittest.TestCase):
    def test_id_format_and_hash(self):
        self.assertEqual(lottery.fmt_id(1), "0001")
        self.assertEqual(lottery.fmt_id("12"), "0012")
        self.assertEqual(lottery.fmt_id("123"), "0123")
        s, d = lottery.hash_item(["lingfes2027","A","58000.01","0001"])
        self.assertEqual(s, "lingfes2027|A|58000.01|0001")
        self.assertEqual(d, hashlib.sha256(s.encode()).hexdigest())
        with self.assertRaises(ValueError): lottery.fmt_id("A123")

    def test_nikkei_close_date_and_mode(self):
        with self.assertRaisesRegex(ValueError,"16:00"):
            lottery.obtain_nikkei_close("final", now=datetime(2027,2,1,15,59,tzinfo=lottery.JST))
        self.assertEqual(lottery.obtain_nikkei_close("auto",now=datetime(2027,1,20,tzinfo=lottery.JST),override="58,123.456"),
                         ("手入力（予行演習）","58123.46","PREVIEW"))
        with self.assertRaisesRegex(ValueError,"手入力終値"):
            lottery.obtain_nikkei_close("final", now=datetime(2027,2,2,tzinfo=lottery.JST),override="58000.01")

    def test_form_headers_and_xlsx_loading(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"forms.xlsx"
            write_test_xlsx(p,[form_row(1),form_row(2,slot="C")])
            rows=lottery.read_forms_export(p)
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]["id"],"0001")
            self.assertEqual(rows[1]["slot"],"C")
            self.assertEqual(rows[0]["onsite"],"SEAT_REQUEST")

    def test_cancel_replaces_record_not_gallery(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            write_test_xlsx(p,[form_row(1,name="同じ人",email="x@example.org"),
                               form_row(2,name="同じ人",email="x@example.org",action="申込取消",old="1")])
            rows=lottery.read_forms_export(p)
            lottery.classify_submissions(rows)
            self.assertEqual([r["status"] for r in rows],["CANCELLED","CANCEL_REQUEST"])

    def test_update_changes_slot_and_keeps_latest(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            write_test_xlsx(p,[form_row(1,name="同じ人",email="x@example.org"),
                               form_row(2,slot="C",name="同じ人",email="x@example.org",action="申込修正（上書き）",old="1")])
            rows=lottery.read_forms_export(p)
            lottery.classify_submissions(rows)
            self.assertEqual([r["status"] for r in rows],["SUPERSEDED","ACTIVE"])
            self.assertEqual(rows[1]["slot"],"C")

    def test_update_wrong_identity_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            write_test_xlsx(p,[form_row(1),form_row(2,action="申込取消",old="1")])
            rows=lottery.read_forms_export(p)
            with self.assertRaisesRegex(ValueError,"一致しません"):
                lottery.classify_submissions(rows)

    def test_test_registration_does_not_overwrite_real_application(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            rows=[form_row(1,name="共通",email="a@example.org"),form_row(2,name="共通",email="t@example.org")]
            write_test_xlsx(p,rows)
            with patch.object(lottery,"TEST_REGISTRATION_REJECT_IDS",[2]):
                r=lottery.read_forms_export(p)
                lottery.classify_submissions(r)
            self.assertEqual([x["status"] for x in r],["ACTIVE","REJECT_TEST"])

    def test_manual_multiple_reject_web_public_not_test(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            write_test_xlsx(p,[form_row(1),form_row(2),form_row(3)])
            r=lottery.read_forms_export(p)
            with patch.multiple(lottery,MULTIPLE_APPLICATION_REJECT_IDS=[2],TEST_REGISTRATION_REJECT_IDS=[3]):
                lottery.classify_submissions(r)
            self.assertEqual(r[1]["status"],"REJECT_MULTIPLE")
            self.assertEqual(r[2]["status"],"REJECT_TEST")

    def test_coauthor_same_slot_gallery_other_slot_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            write_test_xlsx(p,[form_row(1,name="第一",coauthors="共著者（架空大）"),
                               form_row(2,slot="C",name="第三",coauthors="共著者（他大学）"),
                               form_row(3,slot="A",name="第二",coauthors="共著者（架空大）")])
            r=lottery.read_forms_export(p);lottery.classify_submissions(r)
            self.assertEqual([x["status"] for x in r],["GALLERY_COAUTHOR","ACTIVE","ACTIVE"])

    def test_late_cancel_cannot_cancel_before_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            write_test_xlsx(p,[form_row(1,name="人",email="x@example.org"),
                               form_row(2,name="人",email="x@example.org",action="申込取消",old="1",date="2027-02-01 12:01:00")])
            r=lottery.read_forms_export(p);lottery.classify_submissions(r)
            self.assertEqual([x["status"] for x in r],["ACTIVE","REJECT_LATE"])

    def test_three_draw_capacities_and_poster_priority(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            rows=[form_row(i,slot="A" if i<=48 else ("B" if i<=91 else "C"),
                           onsite=ONSITE_OUT if i in (40,41) else ONSITE_YES)
                  for i in range(1,135)]
            write_test_xlsx(p,rows)
            r=lottery.read_forms_export(p);lottery.classify_submissions(r)
            booth=lottery.assign_booths(r,"58000.01")
            poster=lottery.assign_posters(r,"58000.01")
            onsite=lottery.assign_onsite(r,"58000.01")
            self.assertEqual([sum(x["booth_result"]=="ブース採択" for x in booth[s]) for s in lottery.SLOTS], [36,36,36])
            self.assertEqual([sum(x["poster_result"]=="現地ポスター採択" for x in poster[s]) for s in lottery.SLOTS], [8,8,8])
            self.assertEqual(len(onsite["selected"]),32)
            self.assertLessEqual(sum(x["priority_poster"] for x in onsite["selected"]),24)
            self.assertTrue(all(x["priority_poster"] for x in onsite["ranked"][:24]))
            self.assertEqual(len(onsite["outside"]),2)
            self.assertFalse(any(x["status"]=="GALLERY_OVERFLOW" and x["poster_result"]=="現地ポスター採択" for x in r))
            self.assertEqual(len([x for x in r if x["status"]=="GALLERY_OVERFLOW"]),134-108)

    def test_cross_slot_same_person_only_one_onsite_seat(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            rows=[form_row(1,slot="A",name="共通者",email="same@example.org"),
                  form_row(2,slot="C",name="共通者",email="same@example.org")]
            write_test_xlsx(p,rows)
            r=lottery.read_forms_export(p); lottery.classify_submissions(r)
            lottery.assign_booths(r,"58000.01"); lottery.assign_posters(r,"58000.01")
            onsite=lottery.assign_onsite(r,"58000.01")
            self.assertEqual(len(onsite["people"]),1)
            self.assertEqual(onsite["people"][0]["person_id"],"0001")

    def test_person_onsite_outside_no_seat_consumed(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/"r.xlsx"
            rows=[form_row(1,onsite=ONSITE_OUT),form_row(2,onsite=ONSITE_YES)]
            write_test_xlsx(p,rows)
            r=lottery.read_forms_export(p); lottery.classify_submissions(r)
            lottery.assign_booths(r,"58000.01"); lottery.assign_posters(r,"58000.01")
            onsite=lottery.assign_onsite(r,"58000.01")
            self.assertEqual(len(onsite["outside"]),1)
            self.assertEqual(len(onsite["selected"]),1)

    def test_end_to_end_private_public_separation(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            p=root/"forms.xlsx"
            rows=[form_row(i,slot="A" if i<=41 else "B") for i in range(1,55)]
            write_test_xlsx(p,rows)
            with patch.multiple(lottery,MULTIPLE_APPLICATION_REJECT_IDS=[2],TEST_REGISTRATION_REJECT_IDS=[3]):
                report=lottery.run_draw(p,root/"result",mode="preview",manual_price="58,123.45")
            self.assertEqual(report["phase"],"PREVIEW")
            self.assertTrue((root/"result/internal_private/全受付履歴_内部用.csv").exists())
            self.assertTrue((root/"result/web_public/現地配信抽選順位_匿名.csv").exists())
            page=(root/"result/web_public/index.html").read_text(encoding="utf-8")
            self.assertNotIn("person1@example.org",page)
            self.assertNotIn("架空発表者1",page)
            self.assertIn("0002",page)
            self.assertNotIn("0003",page)
            self.assertIn("公開禁止",page)
            self.assertNotIn("<script",page.lower())
            self.assertEqual(json.loads((root/"result/web_public/抽選条件_公開用.json").read_text(encoding="utf-8"))["draw_date"],"2027-02-01")
            for item in (root/"result/web_public").iterdir():
                if item.suffix in (".csv",".html"):
                    self.assertNotIn("person1@example.org",item.read_text(encoding="utf-8-sig"))


if __name__ == "__main__": unittest.main()
