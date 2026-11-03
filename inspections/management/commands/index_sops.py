from django.core.management.base import BaseCommand, CommandError

from inspections import sop_index, sop_loader


class Command(BaseCommand):
    help = 'Index the SOP PDFs named in product_sop_mapping.csv. Safe to run many times.'

    def handle(self, *args, **options):
        try:
            products, passages, problems = sop_index.build_index()
        except sop_loader.MissingEvidence as error:
            raise CommandError(str(error))
        for problem in problems:
            self.stderr.write(self.style.WARNING(f'Skipped {problem}'))
        self.stdout.write(self.style.SUCCESS(
            f'Indexed {passages} passages for {products} product(s) '
            f'using the {sop_index.backend()} backend.'
        ))
