"""株価ネットワーク不要のユニットテスト。公開判定に関係する境界条件を検証。"""
import hashlib
import importlib.util
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lingfes2027_lottery', ROOT / 'lingfes2027_lottery.py')
lottery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lottery)


class LotteryRuleTests(unittest.TestCase):
    def row(self, n, slot, authors, title=None):
        return {'application_no': f'{n:04d}', 'slot': slot, 'authors': authors,
                'title': title or f'試験用題目{n}'}

    def run_classification(self, rows, multiple=None, test=None, gallery=None, last=200):
        overrides = {
            'MAX_APPLICATION_NUMBER': 9999,
            'LAST_PRESENTER_ID': last,
            'MULTIPLE_APPLICATION_REJECT_IDS': multiple or [],
            'TEST_REGISTRATION_REJECT_IDS': test or [],
            'COAUTHOR_GALLERY_MOVE_IDS': gallery or [],
        }
        with patch.multiple(lottery, **overrides):
            lottery.validate_applications(rows)
            info=lottery.determine_validity(rows)
        return rows, info

    def test_id_padding_and_common_serial(self):
        with patch.object(lottery, 'MAX_APPLICATION_NUMBER', 9999):
            self.assertEqual(lottery.id_string('1'), '0001')
            self.assertEqual(lottery.id_string(19), '0019')
            self.assertEqual(lottery.id_string('9999'), '9999')
            with self.assertRaises(ValueError): lottery.id_string('A001')
            with self.assertRaises(ValueError): lottery.id_string('0000')
            with self.assertRaises(ValueError): lottery.id_string('10000')

    def test_duplicate_numbers_across_slots_is_bad_input(self):
        with self.assertRaisesRegex(ValueError,'重複'):
            self.run_classification([self.row(1,'A','a'),self.row(1,'B','b')])

    def test_older_coauthor_goes_gallery_not_reject(self):
        rows,_=self.run_classification([
            self.row(1,'A','山田太郎;佐藤花子'),
            self.row(2,'C','山田太郎;鈴木'),
            self.row(3,'B','山田太郎'),
            self.row(4,'A','佐藤花子;田中'),
        ])
        self.assertEqual([r['status'] for r in rows], ['GALLERY_COAUTHOR','LOTTERY','LOTTERY','LOTTERY'])
        self.assertIn('0004', rows[0]['reason'])
        self.assertEqual(rows[0]['valid'],False)

    def test_author_overlap_chain_latest_per_author(self):
        rows, d = self.run_classification([
            self.row(1,'A','X;Y'),
            self.row(2,'A','X;Z'),
            self.row(3,'A','Y;Z'),
        ])
        self.assertEqual([r['status'] for r in rows], ['GALLERY_COAUTHOR','GALLERY_COAUTHOR','LOTTERY'])
        self.assertEqual(d['latest_by_slot_author'][('A','x')], '0002')
        self.assertEqual(d['latest_by_slot_author'][('A','z')], '0003')

    def test_multiple_reject_and_test_excluded_from_coauthor_recency(self):
        rows,_=self.run_classification([
            self.row(1,'A','X'),
            self.row(2,'A','X'),   # 明示的にRejectするため有効申込を潰さない
            self.row(3,'A','X'),   # 試験登録のため同様に無視する
            self.row(4,'B','X'),   # 別枠なので可
        ],multiple=['0002'],test=['3'])
        self.assertEqual([r['status'] for r in rows], ['LOTTERY','REJECT_MULTIPLE','REJECT_TEST','LOTTERY'])

    def test_manual_gallery_moves_valid_latest_away_without_reinstatement(self):
        rows,_=self.run_classification([
            self.row(1,'A','X'),
            self.row(2,'A','X'),
            self.row(3,'A','Y'),
        ],gallery=['2'])
        self.assertEqual([r['status'] for r in rows], ['GALLERY_COAUTHOR','GALLERY_MANUAL','LOTTERY'])

    def test_user_lists_must_not_overlap_or_refer_to_missing_ids(self):
        for opts in [dict(multiple=['1'],test=['0001']), dict(gallery=['9'])]:
            with self.subTest(opts=opts),self.assertRaisesRegex(ValueError,'両方|存在しません'):
                self.run_classification([self.row(1,'A','X')],**opts)

    def test_last_registration_id_limits_csv(self):
        with self.assertRaisesRegex(ValueError,'LAST_PRESENTER_ID'):
            self.run_classification([self.row(11,'B','X')],last=10)

    def test_score_hash_ascending_and_each_slot_separate(self):
        rows,_=self.run_classification([
            self.row(1,'A','X'),self.row(2,'B','X'),self.row(3,'C','X'),self.row(4,'A','Y')
        ])
        literal,digest=lottery.sha256_for('A','58123.45','0001')
        self.assertEqual(literal,'lingfes2027|A|58123.45|0001')
        self.assertEqual(digest,hashlib.sha256(literal.encode('utf-8')).hexdigest())
        ranks=lottery.make_ranking(rows,'2027-02-02','58123.45','PREVIEW')
        a=[r['sha256'] for r in ranks if r['slot']=='A']
        self.assertEqual(a,sorted(a))
        self.assertEqual(len(ranks),4)

    def test_public_page_contains_reject_but_not_names_or_test_ids(self):
        rows,_=self.run_classification([
            self.row(1,'A','SecretAuthor1'),
            self.row(2,'A','SecretAuthor1'),
            self.row(3,'A','SecretAuthor2'),
            self.row(4,'B','SecretAuthor4'),
        ],multiple=[3],test=[4])
        ranks=lottery.make_ranking(rows,'2026-11-20','58123.45','PREVIEW')
        with patch.object(lottery,'PUBLIC_INCLUDE_TITLES',False):
            html=lottery.make_public_html(rows,ranks,'2026-11-20','58123.45','PREVIEW')
        self.assertIn('多重申込によるReject一覧',html)
        self.assertIn('0003',html)
        self.assertIn('0001',html)  # 先の共著重複はギャラリーで掲載
        self.assertNotIn('0004',html)  # 試験用の受付番号は非公開
        self.assertNotIn('SecretAuthor',html)
        self.assertNotIn('<script',html.lower())
        self.assertIn('公開しないでください',html)
        self.assertIn('noindex',html)

    def test_end_to_end_sample_creates_separate_csv_and_html(self):
        records=[self.row(1,'A','X'),self.row(2,'A','X'),
                 self.row(3,'B','Y'),self.row(4,'C','Z'),
                 self.row(5,'A','reject'),self.row(6,'A','test'),
                 self.row(7,'A','manual')]
        with tempfile.TemporaryDirectory() as t, patch.multiple(lottery,
            MAX_APPLICATION_NUMBER=20,LAST_PRESENTER_ID=7,
            MULTIPLE_APPLICATION_REJECT_IDS=['0005'],
            TEST_REGISTRATION_REJECT_IDS=['0006'],
            COAUTHOR_GALLERY_MOVE_IDS=['0007'],INPUT_MODE='demo',OUTPUT_DIR_NAME='out'), \
             patch.object(lottery,'load_applications',return_value=records), \
             patch.object(lottery,'obtain_nikkei_close',return_value=('2026-11-19','58123.45','PREVIEW')):
            cwd=os.getcwd()
            os.chdir(t)
            try:
                lottery.main()
            finally:
                os.chdir(cwd)
            root=pathlib.Path(t)/'out'
            for name in ('多重申込Reject_内部用.csv','試験登録Reject_内部用.csv',
                         '共著申込ギャラリー移動_内部用.csv',
                         '定員超過_ギャラリー対象_内部用.csv',
                         '共著者別_最後の発表者ID_内部用.csv',
                         '多重申込Reject_公開用.csv','web_public/index.html',
                         'web_public/共著者重複_ギャラリー移動一覧.csv',
                         'web_public/多重申込Reject一覧.csv',
                         'web_public/抽選条件_公開用.json',
                         '抽選実行条件.json'):
                self.assertTrue((root/name).exists(),name)
            h=(root/'web_public/index.html').read_text(encoding='utf-8')
            self.assertNotIn('reject</td>',h)
            self.assertNotIn('SecretAuthor',h)
            self.assertIn('0005',h)
            self.assertNotIn('繰上げ候補', h)
            self.assertFalse((root/'定員超過_繰上げ候補_内部用.csv').exists())
            # Web公開専用フォルダには内部用の氏名つき台帳を入れない。
            public_files={p.name for p in (root/'web_public').iterdir()}
            self.assertFalse(any('内部用' in name for name in public_files))
            with (root/'web_public/抽選条件_公開用.json').open(encoding='utf-8') as f:
                import json
                public_config=json.load(f)
            self.assertNotIn('manual_lists', public_config)
            self.assertNotIn('sha256_private_application_decisions', public_config)


    def test_consecutive_common_author_across_slots_allowed(self):
        # A / B / Cの別枠なら同じ研究者の発表を妨げない。
        rows, _ = self.run_classification([
            self.row(10, 'A', '共通著者X'),
            self.row(11, 'B', '共通著者X'),
            self.row(12, 'C', '共通著者X'),
        ])
        self.assertTrue(all(r['status'] == 'LOTTERY' for r in rows))

    def test_public_gallery_csv_and_private_test_separation(self):
        # 公開ディレクトリ内のCSVに内部用の著者列や試験番号を含めない。
        import csv
        records = [self.row(1,'A','X'), self.row(2,'A','X'),
                   self.row(3,'A','Rejected'), self.row(4,'A','Tester')]
        with tempfile.TemporaryDirectory() as t, patch.multiple(lottery,
            MAX_APPLICATION_NUMBER=20, LAST_PRESENTER_ID=4,
            MULTIPLE_APPLICATION_REJECT_IDS=['0003'],
            TEST_REGISTRATION_REJECT_IDS=['0004'],
            COAUTHOR_GALLERY_MOVE_IDS=[],
            INPUT_MODE='demo', OUTPUT_DIR_NAME='out'), \
             patch.object(lottery, 'load_applications', return_value=records), \
             patch.object(lottery, 'obtain_nikkei_close', return_value=('2026-11-19','58123.45','PREVIEW')):
            old=os.getcwd()
            os.chdir(t)
            try:
                lottery.main()
            finally:
                os.chdir(old)
            folder=pathlib.Path(t)/'out'/'web_public'
            for filename in ('多重申込Reject一覧.csv','共著者重複_ギャラリー移動一覧.csv'):
                with (folder/filename).open(encoding='utf-8-sig',newline='') as f:
                    columns=next(csv.reader(f))
                self.assertNotIn('authors',columns)
                self.assertNotIn('title',columns)
            gallery=(folder/'共著者重複_ギャラリー移動一覧.csv').read_text(encoding='utf-8-sig')
            self.assertIn('0001',gallery)
            self.assertNotIn('0004',gallery)
            public_html=(folder/'index.html').read_text(encoding='utf-8')
            self.assertIn('0003',public_html)
            self.assertNotIn('>0004<',public_html)


    def test_capacity_37th_is_gallery_and_no_waitlist(self):
        # 定員36件を超えた場合、37位はギャラリー対象。繰上げはない。
        rows = [self.row(i, 'A', f'Person{i}') for i in range(1, 40)]
        rows, _ = self.run_classification(rows, last=39)
        with patch.object(lottery, 'BOOTH_CAPACITY', 36):
            ranked = lottery.make_ranking(rows, '2027-02-02', '58123.45', 'FINAL')
            self.assertEqual(len([r for r in ranked if r['result'] == 'ブース割当候補']), 36)
            overflow = [r for r in ranked if r['result'] == 'フェス・ギャラリー対象（定員超過）']
            self.assertEqual(len(overflow), 3)
            self.assertEqual([r['rank'] for r in overflow], [37, 38, 39])
            html = lottery.make_public_html(rows, ranked, '2027-02-02', '58123.45', 'FINAL')
            self.assertIn('繰上げ採択は行いません', html)
            self.assertNotIn('繰上げ候補', html)
            self.assertNotIn('繰り上げます', html)


if __name__ == '__main__':
    unittest.main()
