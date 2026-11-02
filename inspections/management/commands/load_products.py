import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from inspections.models import Product

DEFAULT_CSV = Path(settings.BASE_DIR) / 'pack_data' / 'product_details.csv'


class Command(BaseCommand):
    help = 'Create or update products from product_details.csv. Safe to run many times.'

    def add_arguments(self, parser):
        parser.add_argument('--csv', default=str(DEFAULT_CSV))

    def handle(self, *args, **options):
        path = Path(options['csv'])
        if not path.exists():
            raise CommandError(f'Product file not found: {path}')
        with path.open(newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                product, created = Product.objects.update_or_create(
                    product_id=row['product_id'].strip(),
                    defaults={
                        'name': row['product_name'].strip(),
                        'description': row['description'].strip(),
                    },
                )
                self.stdout.write(f"{'Created' if created else 'Already present, updated'}: {product}")
