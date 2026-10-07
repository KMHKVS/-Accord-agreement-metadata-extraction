"""Batch prediction, exact-match evaluation and a read-only dataset audit."""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

from .config import DEFAULT_PROVIDER, PROVIDERS, ROOT, server_key
from .extraction import extract
from .readers import EXTENSIONS, prepare_document
from .schemas import FIELDS


def document_id(name: str) -> str:
    path = Path(name)
    # Handle supplied names such as document.pdf.docx without altering ordinary IDs.
    while path.suffix.lower() in EXTENSIONS:
        path = Path(path.stem)
    return path.name


def load_rows(path: Path) -> dict:
    with path.open(newline='', encoding='utf-8-sig') as stream:
        reader = csv.DictReader(stream)
        required = {'File Name', *FIELDS.values()}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f'{path} must include columns: {", ".join(required)}')
        rows = {}
        for row in reader:
            key = document_id(row['File Name'])
            if key in rows:
                raise ValueError(f'Duplicate document ID: {key}')
            rows[key] = row
    return rows


def evaluate(predictions: Path, labels: Path) -> dict:
    predicted, expected = load_rows(predictions), load_rows(labels)
    metrics, mismatches = {}, []
    for column in FIELDS.values():
        exact, trimmed, count = 0, 0, 0
        for key, row in expected.items():
            truth = row[column] or ''
            if not truth.strip():
                continue  # Unknown ground truth cannot establish correctness.
            count += 1
            guess = predicted.get(key, {}).get(column) or ''
            exact += int(guess == truth)
            trimmed += int(guess.strip() == truth.strip())
            if guess != truth:
                mismatches.append({'file': key, 'field': column, 'expected': truth, 'predicted': guess})
        metrics[column] = {'exact_matches': exact, 'labelled_values': count,
                           'recall': exact / count if count else None,
                           'whitespace_trimmed_recall': trimmed / count if count else None}
    return {'documents': len(expected), 'metrics': metrics,
            'missing_predictions': sorted(set(expected) - set(predicted)),
            'extra_predictions': sorted(set(predicted) - set(expected)),
            'mismatches': mismatches,
            'policy': 'Primary metric is literal exact-match recall. Blank ground truth is excluded per field. Missing predictions count as failures. Trimmed scores are supplementary only.'}


def audit(data_dir: Path) -> dict:
    report, labels = {}, {}
    for split in ('train', 'test'):
        rows = load_rows(data_dir / f'{split}.csv')
        labels[split] = rows
        paths = [p for p in (data_dir / split).iterdir() if p.suffix.lower() in EXTENSIONS]
        files = {document_id(p.name) for p in paths}
        invalid_dates, blank_labels = [], []
        for key, row in rows.items():
            for field in ('Aggrement Start Date', 'Aggrement End Date'):
                if row[field].strip():
                    try:
                        datetime.strptime(row[field].strip(), '%d.%m.%Y')
                    except ValueError:
                        invalid_dates.append({'file': key, 'field': field, 'value': row[field]})
            for field in FIELDS.values():
                if not row[field].strip():
                    blank_labels.append({'file': key, 'field': field})
        report[split] = {'files': len(paths), 'label_rows': len(rows),
                         'labels_without_file': sorted(set(rows) - files),
                         'files_without_labels': sorted(files - set(rows)),
                         'invalid_dates': invalid_dates, 'blank_labels': blank_labels}
    report['overlapping_label_ids'] = sorted(set(labels['train']) & set(labels['test']))
    return report


def predict(folder: Path, output: Path, model: str, provider: str = DEFAULT_PROVIDER) -> int:
    key = server_key(provider)
    if not key:
        raise ValueError(f'Set {PROVIDERS[provider]["key_env"]} in .env before generating predictions. No predictions or scores have been fabricated.')
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if not paths:
        raise ValueError('No supported documents found in this folder.')
    ids = [document_id(p.name) for p in paths]
    if len(ids) != len(set(ids)):
        raise ValueError('Multiple files have the same document ID. Put alternate versions in separate folders.')
    output.parent.mkdir(parents=True, exist_ok=True)
    records, details, errors = [], [], []
    for path in paths:
        row = {'File Name': document_id(path.name), **{column: '' for column in FIELDS.values()}}
        try:
            doc = prepare_document(path.name, path.read_bytes())
            result = extract(doc, key, model, provider)
            row.update({column: getattr(result, field).value or '' for field, column in FIELDS.items()})
            details.append({'filename': path.name, 'provider': provider, 'model': model, 'result': result.model_dump()})
            print(f'Extracted: {path.name}')
        except Exception as exc:
            errors.append({'filename': path.name, 'error': str(exc)})
            print(f'Failed: {path.name}: {exc}', file=sys.stderr)
        records.append(row)
    with output.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['File Name', *FIELDS.values()])
        writer.writeheader()
        writer.writerows(records)
    output.with_suffix('.json').write_text(json.dumps({'provider': provider, 'model': model, 'documents': details, 'errors': errors}, indent=2), encoding='utf-8')
    print(f'Saved {len(details)} successful predictions and {len(errors)} failures to {output}')
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prediction = sub.add_parser('predict', help='Extract folder contents without reading labels')
    prediction.add_argument('folder', type=Path)
    prediction.add_argument('--output', type=Path, default=ROOT / 'output/test_predictions.csv')
    prediction.add_argument('--provider', choices=PROVIDERS, default=DEFAULT_PROVIDER)
    prediction.add_argument('--model', default=None)
    evaluation = sub.add_parser('evaluate', help='Compute per-field exact-match recall')
    evaluation.add_argument('--predictions', type=Path, required=True)
    evaluation.add_argument('--labels', type=Path, default=ROOT / 'data/test.csv')
    evaluation.add_argument('--output', type=Path, default=ROOT / 'output/metrics.json')
    auditing = sub.add_parser('audit', help='Report dataset inconsistencies without changing data')
    auditing.add_argument('--data', type=Path, default=ROOT / 'data')
    args = parser.parse_args()
    try:
        if args.command == 'predict':
            return predict(args.folder, args.output, args.model or PROVIDERS[args.provider]['model'], args.provider)
        result = evaluate(args.predictions, args.labels) if args.command == 'evaluate' else audit(args.data)
        if args.command == 'evaluate':
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
