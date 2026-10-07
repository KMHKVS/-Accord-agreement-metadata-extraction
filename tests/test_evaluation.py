import csv

import pytest

from app.cli import audit, document_id, evaluate
from app.config import ROOT
from app.schemas import FIELDS


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['File Name', *FIELDS.values()])
        writer.writeheader(); writer.writerows(rows)


def test_missing_prediction_counts_and_blank_truth_is_excluded(tmp_path):
    labels, predictions = tmp_path / 'labels.csv', tmp_path / 'predictions.csv'
    write_csv(labels, [{'File Name': 'a', 'Party One': ' Alice '}, {'File Name': 'b', 'Party One': 'Bob'}])
    write_csv(predictions, [{'File Name': 'a.docx', 'Party One': 'Alice'}])
    report = evaluate(predictions, labels)
    assert report['metrics']['Party One']['recall'] == 0
    assert report['metrics']['Party One']['whitespace_trimmed_recall'] == .5
    assert report['metrics']['Aggrement Value']['recall'] is None
    assert report['missing_predictions'] == ['b']


def test_compound_extensions_and_dataset_audit():
    assert document_id('156155545-Rental-Agreement-Kns-Home.pdf.docx') == '156155545-Rental-Agreement-Kns-Home'
    report = audit(ROOT / 'data')
    assert report['overlapping_label_ids'] == ['24158401-Rental-Agreement']
    assert len(report['train']['invalid_dates']) == 3
    assert len(report['train']['files_without_labels']) == 1


def test_duplicate_ids_are_not_silently_overwritten(tmp_path):
    path = tmp_path / 'bad.csv'
    write_csv(path, [{'File Name': 'a'}, {'File Name': 'a.docx'}])
    with pytest.raises(ValueError, match='Duplicate'):
        evaluate(path, path)
