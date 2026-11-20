"""Offline verification tests; never require a stock-price data connection."""
import hashlib
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('lingfes2027_lottery', ROOT / 'lingfes2027_lottery.py')
lottery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lottery)


class LotteryRuleTests(unittest.TestCase):
    def row(self, n, slot, authors):
        return {'application_no': f'{n:04d}', 'slot': slot,
                'authors': authors, 'title': f'Sample {n}'}

    def prepare(self, rows):
        lottery.validate_applications(rows)
        lottery.determine_validity(rows)
        return rows

    def test_application_id_is_global_and_four_digit(self):
        self.assertEqual(lottery.id_string('1'), '0001')
        self.assertEqual(lottery.id_string('0007'), '0007')
        with self.assertRaises(ValueError):
            lottery.id_string('0000')
        with self.assertRaises(ValueError):
            lottery.id_string('A001')

    def test_last_submission_wins_within_one_slot_only(self):
        rows = self.prepare([
            self.row(1, 'A', '山田太郎;佐藤花子'),
            self.row(2, 'C', '山田太郎;鈴木'),
            self.row(3, 'B', '山田太郎'),
            self.row(4, 'A', '佐藤花子;田中'),
        ])
        self.assertEqual([r['valid'] for r in rows], [False, True, True, True])
        self.assertIn('0004', rows[0]['invalid_reason'])

    def test_any_shared_author_invalidates_earlier_entry(self):
        rows = self.prepare([
            self.row(10, 'A', 'a;b'),
            self.row(20, 'A', 'a;c'),
            self.row(30, 'A', 'b;c'),
        ])
        self.assertEqual([r['valid'] for r in rows], [False, False, True])

    def test_hash_format_and_ascending_rank(self):
        rows = self.prepare([self.row(1,'A','a'), self.row(3,'A','b'), self.row(4,'C','a')])
        source,digest = lottery.sha256_for('A', '58123.45', '0001')
        self.assertEqual(source, 'lingfes2027|A|58123.45|0001')
        self.assertEqual(digest, hashlib.sha256(source.encode('utf-8')).hexdigest())
        results = lottery.make_ranking(rows, '2027-02-02', '58123.45', 'PREVIEW')
        a_rows = [r for r in results if r['slot'] == 'A']
        self.assertEqual([r['rank'] for r in a_rows], [1,2])
        self.assertEqual([r['sha256'] for r in a_rows], sorted(x['sha256'] for x in a_rows))
        self.assertEqual(len([r for r in results if r['slot'] == 'C']),1)

    def test_duplicate_global_numbers_rejected_even_different_slots(self):
        with self.assertRaisesRegex(ValueError, '重複'):
            lottery.validate_applications([self.row(1, 'A','a'), self.row(1,'C','b')])

if __name__ == '__main__':
    unittest.main()
