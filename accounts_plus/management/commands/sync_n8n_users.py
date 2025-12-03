from django.core.management.base import BaseCommand
from django.contrib.auth.models import User

from accounts_plus.models import UserN8NProfile
from n8n_mirror.models import UserEntity, UserApiKeys


class Command(BaseCommand):
    help = "Sync Django users with n8n users by matching email addresses"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Update existing profiles even if they already have n8n_user_id',
        )
        parser.add_argument(
            '--delete-orphans',
            action='store_true',
            help='Delete Django users who do not exist in n8n',
        )
        parser.add_argument(
            '--keep-superusers',
            action='store_true',
            default=True,
            help='Keep superuser accounts even if not in n8n (default: True)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        force = options['force']
        delete_orphans = options['delete_orphans']
        keep_superusers = options['keep_superusers']

        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN - No changes will be made\n'))

        # Get all n8n users indexed by email
        n8n_users = {}
        for n8n_user in UserEntity.objects.all():
            if n8n_user.email:
                n8n_users[n8n_user.email.lower()] = n8n_user

        self.stdout.write(f"Found {len(n8n_users)} n8n users with emails\n")

        # Get all API keys indexed by user ID
        api_keys = {}
        for api_key in UserApiKeys.objects.all():
            user_id = str(api_key.userId_id)
            if user_id not in api_keys:
                api_keys[user_id] = api_key.apiKey

        self.stdout.write(f"Found {len(api_keys)} API keys\n")

        # Process Django users
        created = 0
        updated = 0
        skipped = 0
        not_found = 0
        deleted = 0
        users_to_delete = []

        for user in User.objects.all():
            email = user.email.lower() if user.email else None
            
            if not email:
                self.stdout.write(f"  SKIP: {user.username} - no email")
                skipped += 1
                continue

            # Check if user exists in n8n
            n8n_user = n8n_users.get(email)
            if not n8n_user:
                self.stdout.write(self.style.WARNING(
                    f"  NOT FOUND: {user.username} ({email}) - no matching n8n user"
                ))
                not_found += 1
                
                # Mark for deletion if flag is set
                if delete_orphans:
                    if user.is_superuser and keep_superusers:
                        self.stdout.write(self.style.NOTICE(
                            f"    -> KEPT: {user.username} is a superuser"
                        ))
                    else:
                        users_to_delete.append(user)
                continue

            n8n_user_id = str(n8n_user.id)
            api_key = api_keys.get(n8n_user_id, '')

            # Check if profile exists
            try:
                profile = UserN8NProfile.objects.get(user=user)
                
                # Skip if already has n8n_user_id and not forcing
                if profile.n8n_user_id and not force:
                    self.stdout.write(f"  EXISTS: {user.username} - already has n8n_user_id: {profile.n8n_user_id}")
                    skipped += 1
                    continue

                # Update existing profile
                if not dry_run:
                    profile.n8n_user_id = n8n_user_id
                    if api_key:
                        profile.api_key = api_key
                    profile.save()
                
                self.stdout.write(self.style.SUCCESS(
                    f"  UPDATED: {user.username} -> n8n_user_id: {n8n_user_id}, api_key: {'yes' if api_key else 'no'}"
                ))
                updated += 1

            except UserN8NProfile.DoesNotExist:
                # Create new profile
                if not dry_run:
                    UserN8NProfile.objects.create(
                        user=user,
                        n8n_user_id=n8n_user_id,
                        api_key=api_key,
                    )
                
                self.stdout.write(self.style.SUCCESS(
                    f"  CREATED: {user.username} -> n8n_user_id: {n8n_user_id}, api_key: {'yes' if api_key else 'no'}"
                ))
                created += 1

        # Delete orphan users
        if delete_orphans and users_to_delete:
            self.stdout.write('\n' + '-' * 50)
            self.stdout.write(self.style.ERROR('DELETING ORPHAN USERS:'))
            for user in users_to_delete:
                self.stdout.write(self.style.ERROR(f"  DELETE: {user.username} ({user.email})"))
                if not dry_run:
                    user.delete()
                deleted += 1

        # Summary
        self.stdout.write('\n' + '=' * 50)
        self.stdout.write(self.style.SUCCESS(f"Created: {created}"))
        self.stdout.write(self.style.SUCCESS(f"Updated: {updated}"))
        self.stdout.write(self.style.WARNING(f"Skipped: {skipped}"))
        self.stdout.write(self.style.WARNING(f"Not found in n8n: {not_found}"))
        if delete_orphans:
            self.stdout.write(self.style.ERROR(f"Deleted: {deleted}"))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No changes were made. Run without --dry-run to apply.'))
