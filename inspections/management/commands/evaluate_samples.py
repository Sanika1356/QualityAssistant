import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inspections.model.inference import MODEL_VERSION, predict
from inspections.validators import validate_image

SAMPLES_DIR = Path(settings.BASE_DIR) / 'pack_data' / 'Samples'
REPORT_PATH = Path(settings.BASE_DIR) / 'metrics_report.txt'
CLASSES = ('Normal', 'Defective')


class Command(BaseCommand):
    help = 'Score the frozen model on the labelled sample images (Validation files are excluded).'

    def add_arguments(self, parser):
        parser.add_argument('--samples', default=str(SAMPLES_DIR))
        parser.add_argument('--output', default=str(REPORT_PATH))

    def handle(self, *args, **options):
        samples_dir = Path(options['samples'])
        images_dir = samples_dir / 'images'
        labels_path = samples_dir / 'labels.csv'
        if not images_dir.is_dir() or not labels_path.exists():
            raise CommandError(f'Expected {images_dir} and {labels_path}.')

        # 1. Predict from image content only. Labels are not read until scoring.
        images = sorted(p for p in images_dir.iterdir() if p.is_file())
        predictions, failures = {}, []
        for path in images:
            key = path.relative_to(samples_dir).as_posix()
            reason = validate_image(path)
            if reason:
                failures.append((key, f'rejected by validator: {reason}'))
                continue
            try:
                predictions[key] = predict(path)['predicted_class']
            except Exception as exc:
                failures.append((key, f'predict() raised {type(exc).__name__}: {exc}'))

        # 2. Score against labels.csv.
        with labels_path.open(newline='', encoding='utf-8-sig') as f:
            labels = {row['relative_path'].strip(): row['label'].strip() for row in csv.DictReader(f)}

        matrix = {(a, p): 0 for a in CLASSES for p in CLASSES}
        unlabelled, mistakes = [], []
        for key, predicted in predictions.items():
            actual = labels.get(key)
            if actual not in CLASSES:
                unlabelled.append(key)
                continue
            matrix[(actual, predicted)] += 1
            if actual != predicted:
                mistakes.append((key, actual, predicted))
        never_seen = sorted(set(labels) - {p.relative_to(samples_dir).as_posix() for p in images})

        tp = matrix[('Defective', 'Defective')]
        fn = matrix[('Defective', 'Normal')]
        fp = matrix[('Normal', 'Defective')]
        tn = matrix[('Normal', 'Normal')]
        scored = tp + fn + fp + tn

        lines = [
            'Visual Inspection - sample evaluation',
            f'Model version: {MODEL_VERSION} (decision threshold 0.5, unchanged)',
            f'Images found: {len(images)} | predicted: {len(predictions)} | scored: {scored} | '
            f'failures: {len(failures)}',
            'Validation folder: excluded',
            '',
            'Confusion matrix (rows = actual, columns = predicted)',
            f"{'':>18}{'Normal':>12}{'Defective':>12}",
            f"{'actual Normal':>18}{tn:>12}{fp:>12}",
            f"{'actual Defective':>18}{fn:>12}{tp:>12}",
            '',
            f'TP (defective caught)        = {tp}',
            f'FN (defective missed)        = {fn}',
            f'FP (normal flagged)          = {fp}',
            f'TN (normal passed)           = {tn}',
        ]
        if tp + fn:
            lines.append(f'Defect recall = TP/(TP+FN) = {tp}/{tp + fn} = {tp / (tp + fn):.4f}')
        else:
            lines.append('Defect recall: undefined (no defective images were scored).')
        if scored:
            lines.append(f'Accuracy = (TP+TN)/total = {tp + tn}/{scored} = {(tp + tn) / scored:.4f}')

        lines += ['', 'Failures:']
        lines += [f'  {key}: {why}' for key, why in failures] or ['  none - every image was processed.']
        if unlabelled:
            lines += ['Predicted but missing from labels.csv (not scored):'] + [f'  {k}' for k in unlabelled]
        if never_seen:
            lines += ['Listed in labels.csv but no image file found:'] + [f'  {k}' for k in never_seen]
        lines += ['', 'Misclassified images:']
        lines += [f'  {k}: actual {a}, predicted {p}' for k, a, p in mistakes] or ['  none']

        lines.append('')
        if fn == 0 and tp:
            lines.append(
                'No false negatives: every defective sample was caught. This is a small synthetic '
                f'sample ({scored} images), so it cannot establish real-world reliability.'
            )
        else:
            lines.append(
                f'{fn} defective image(s) were missed. Note this is a small synthetic sample '
                f'({scored} images) and cannot establish real-world reliability.'
            )

        report = '\n'.join(lines) + '\n'
        Path(options['output']).write_text(report, encoding='utf-8')
        self.stdout.write(report)
        self.stdout.write(f"Saved to {options['output']}")
