from django.conf import settings
from django.core.management.base import BaseCommand

from services.logins import create_missing_logins, write_logins_csv


class Command(BaseCommand):
    help = ("Create a login for every customer, mechanic and staff member who doesn't have one. "
            "Safe to run again any time.")

    def add_arguments(self, parser):
        parser.add_argument('--csv', default=str(settings.BASE_DIR.parent / 'docs' / 'logins.csv'),
                            help='Where to write the list of demo logins')

    def handle(self, *args, **opts):
        made = create_missing_logins()
        n = write_logins_csv(opts['csv'])
        self.stdout.write(self.style.SUCCESS(
            f"Created {made['customer']} customer, {made['mechanic']} mechanic and {made['staff']} staff logins. "
            f"{n} logins listed in {opts['csv']}"))
