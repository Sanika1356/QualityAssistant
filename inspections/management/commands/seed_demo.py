
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group


class Command(BaseCommand):
    help = "Create demo users and role groups"

    def handle(self, *args, **options):

        demo_password = "Demo@12345"

        roles = {
            "demo_admin": "Administrator",
            "demo_engineer": "Engineer",
            "demo_engineer2": "Engineer",
            "demo_supervisor": "Supervisor",
        }

        # Create all role groups
        for role in roles.values():
            Group.objects.get_or_create(name=role)

        self.stdout.write(
            self.style.SUCCESS("Role groups created.")
        )

        # Create demo users and assign their groups
        for username, role in roles.items():

            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "is_staff": username == "demo_admin"
                }
            )

            user.set_password(demo_password)

            if username == "demo_admin":
                user.is_staff = True

            user.save()

            group = Group.objects.get(name=role)
            user.groups.add(group)

            self.stdout.write(
                self.style.SUCCESS(
                    f"{'Created' if created else 'Updated'} "
                    f"{username} -> {role}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Demo users and groups are ready!"
            )
        )
