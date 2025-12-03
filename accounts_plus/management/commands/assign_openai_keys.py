"""
Management command to assign OpenAI API keys to existing users who don't have one.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from accounts_plus.models import OpenAIKeyPool


class Command(BaseCommand):
    help = 'Assign OpenAI API keys from the pool to existing users who do not have one assigned'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually assigning keys',
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Assign key to a specific user by email or username',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        specific_user = options.get('user')

        # Get pool stats
        stats = OpenAIKeyPool.get_pool_stats()
        self.stdout.write(f"\n📊 Pool Stats: {stats['available']} available / {stats['total']} total keys")
        self.stdout.write(f"   Assigned: {stats['assigned']}, Inactive: {stats['inactive']}\n")

        if specific_user:
            # Handle single user
            user = User.objects.filter(email=specific_user).first() or \
                   User.objects.filter(username=specific_user).first()
            if not user:
                self.stdout.write(self.style.ERROR(f"❌ User '{specific_user}' not found"))
                return
            users_to_process = [user]
        else:
            # Get all users without an assigned key
            users_with_keys = OpenAIKeyPool.objects.filter(
                assigned_to__isnull=False
            ).values_list('assigned_to_id', flat=True)
            
            users_to_process = User.objects.exclude(id__in=users_with_keys)

        if not users_to_process:
            self.stdout.write(self.style.SUCCESS("✅ All users already have keys assigned!"))
            return

        self.stdout.write(f"Found {len(users_to_process)} user(s) without assigned keys:\n")

        assigned_count = 0
        failed_count = 0

        for user in users_to_process:
            existing_key = OpenAIKeyPool.get_user_key(user)
            if existing_key:
                self.stdout.write(f"  ⏭️  {user.email} - already has key assigned")
                continue

            if dry_run:
                self.stdout.write(f"  🔍 {user.email} - would assign key (dry-run)")
                assigned_count += 1
            else:
                key = OpenAIKeyPool.assign_to_user(user)
                if key:
                    key_preview = f"{key.api_key[:8]}...{key.api_key[-4:]}"
                    self.stdout.write(self.style.SUCCESS(
                        f"  ✅ {user.email} - assigned key {key_preview}"
                    ))
                    assigned_count += 1
                else:
                    self.stdout.write(self.style.ERROR(
                        f"  ❌ {user.email} - no available keys in pool!"
                    ))
                    failed_count += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: Would assign {assigned_count} key(s)"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Assigned {assigned_count} key(s)"))
            if failed_count:
                self.stdout.write(self.style.ERROR(f"Failed to assign {failed_count} key(s) - add more keys to pool"))

        # Show updated stats
        if not dry_run:
            stats = OpenAIKeyPool.get_pool_stats()
            self.stdout.write(f"\n📊 Updated Pool Stats: {stats['available']} available / {stats['total']} total keys\n")
