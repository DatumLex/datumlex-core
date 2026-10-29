"""Synthetic engineering tests, never human validation of judicial content."""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

import nlp_validation as v


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.text = '😀 Súmula 7 do STJ. A responsabilidade civil depende de prova, pois o dano exige nexo.'
        source = self.root / 'source.txt'
        source.write_text(self.text, encoding='utf8')
        digest = hashlib.sha256(self.text.encode()).hexdigest()
        self.row = {'document_id': 'STJ:test', 'court': 'STJ', 'artifact_path': 'source.txt',
                    'artifact_sha256': digest, 'text_sha256': digest, 'publication_date': '2026-01-02'}
        v.save(self.root / 'nlp-local/queue.json', [self.row])
        self.directory = v.prepare(self.root, target=100)
        self.document = v.load_dataset(self.directory)[0]['documents'][0]

    def review(self, reviewer, completed=True):
        start = self.text.index('Súmula')
        end = self.text.index('. ')
        return {'document_id': self.row['document_id'], 'text_sha256': self.row['text_sha256'],
                'reviewer': reviewer, 'completed': completed,
                'annotations': [{'label': 'CITED_AUTHORITY', 'start': start, 'end': end,
                                 'text': self.text[start:end], 'adoption': 'mentioned'}]}

    def test_no_review_is_not_perfect_score(self):
        result = v.evaluate(self.directory)
        self.assertEqual(result['adjudicated_documents'], 0)
        self.assertIsNone(result['splits']['test']['labels']['CITED_AUTHORITY'])
        self.assertEqual(result['release'], 'blocked')

    def test_unicode_and_invented_text(self):
        row = self.review('a')
        v.validate_review(row, self.document)
        row['annotations'][0]['start'] += 1
        with self.assertRaises(ValueError):
            v.validate_review(row, self.document)

    def test_boolean_offset_rejected(self):
        row = self.review('a')
        row['annotations'][0]['start'] = True
        with self.assertRaises(ValueError):
            v.validate_review(row, self.document)

    def test_drafts_and_single_reviewer_do_not_form_gold(self):
        v.store_review(self.directory, self.review('a', False))
        with self.assertRaises(ValueError):
            v.store_review(self.directory, self.review('c'), True)
        v.store_review(self.directory, self.review('a'))
        with self.assertRaises(ValueError):
            v.store_review(self.directory, self.review('c'), True)

    def test_adjudicator_must_be_distinct_case_insensitive(self):
        for reviewer in ('a', 'b'):
            v.store_review(self.directory, self.review(reviewer))
        with self.assertRaises(ValueError):
            v.store_review(self.directory, self.review(' A '), True)

    def test_gold_metrics_are_only_for_adjudicated_documents(self):
        for reviewer in ('a', 'b'):
            v.store_review(self.directory, self.review(reviewer))
        v.store_review(self.directory, self.review('c'), True)
        result = v.evaluate(self.directory)
        self.assertEqual(result['adjudicated_documents'], 1)
        metric = result['splits']['development']['labels']['CITED_AUTHORITY']
        self.assertEqual((metric['tp'], metric['fp'], metric['fn']), (1, 0, 0))
        self.assertIsNone(result['splits']['test']['labels']['CITED_AUTHORITY'])
        self.assertEqual(result['release'], 'blocked')

    def test_edit_review_invalidates_previous_adjudication(self):
        for reviewer in ('a', 'b'):
            v.store_review(self.directory, self.review(reviewer))
        v.store_review(self.directory, self.review('c'), True)
        changed = self.review('b')
        changed['annotations'] = []
        v.store_review(self.directory, changed)
        self.assertEqual(v.evaluate(self.directory)['adjudicated_documents'], 0)
        self.assertTrue(list((self.directory / 'history').glob('*.json')))

    def test_predictions_are_frozen(self):
        path = self.directory / 'predictions.json'
        value = v.read(path)
        value['documents']['STJ:test']['annotations'] = []
        v.save(path, value)
        with self.assertRaisesRegex(ValueError, 'prediction_integrity'):
            v.evaluate(self.directory)

    def test_false_negatives_and_undefined_denominators(self):
        self.assertEqual(v.scores(set(), {('a', 1, 2)})['recall'], 0)
        self.assertIsNone(v.scores(set(), set())['f1'])
        self.assertEqual(v.scores({1, 2}, {1, 3}),
                         {'tp': 1, 'fp': 1, 'fn': 1, 'precision': .5, 'recall': .5, 'f1': .5})

    def test_single_reviewer_diagnostic_never_approves_release(self):
        v.store_review(self.directory, self.review('a'))
        result = v.evaluate(self.directory, single_reviewer='A')
        self.assertEqual(result['single_reviewer_diagnostic']['documents'], 1)
        self.assertEqual(result['single_reviewer_diagnostic']['labels']['CITED_AUTHORITY']['tp'], 1)
        self.assertEqual(result['adjudicated_documents'], 0)
        self.assertEqual(result['release'], 'blocked')
        self.assertTrue(list(self.directory.glob('diagnostic-*.json')))

    def test_process_group_does_not_leak_between_splits(self):
        rows = []
        for i in range(30):
            text = f'Documento independente {i}. '
            (self.root / f'{i}.txt').write_text(text, encoding='utf8')
            row = deepcopy(self.row)
            row.update(document_id=f'STJ:{i}', artifact_path=f'{i}.txt',
                       artifact_sha256=hashlib.sha256(text.encode()).hexdigest(),
                       text_sha256=hashlib.sha256(text.encode()).hexdigest(), process_number=str(i // 2))
            rows.append(row)
        # Fifteen independent processes: all documents remain development-only.
        v.save(self.root / 'nlp-local/queue.json', rows)
        directory = v.prepare(self.root)
        docs = v.load_dataset(directory)[0]['documents']
        self.assertEqual({d['split'] for d in docs}, {'development'})
        for row in rows:
            row['process_number'] = row['document_id']
        v.save(self.root / 'nlp-local/queue.json', rows)
        docs = v.load_dataset(v.prepare(self.root))[0]['documents']
        self.assertEqual({d['split'] for d in docs}, {'development', 'test'})
        groups = {}
        for doc in docs:
            groups.setdefault(doc['group'], set()).add(doc['split'])
        self.assertTrue(all(len(values) == 1 for values in groups.values()))


if __name__ == '__main__':
    unittest.main()
