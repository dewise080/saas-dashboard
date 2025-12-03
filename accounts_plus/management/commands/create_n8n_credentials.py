"""
Management command to create n8n credentials for existing users with connected WhatsApp.
Creates OpenAI API and Evolution API credentials in n8n for users who connected before this feature.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from apps.pages.models import UserWhatsAppInstance
from apps.pages.views import create_n8n_credentials_for_user


class Command(BaseCommand):
    help = 'Create n8n credentials (OpenAI + Evolution API) for existing users with connected WhatsApp instances'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually creating credentials',
        )
        parser.add_argument(
            '--user',
            type=str,
            help='Create credentials for a specific user by email or username',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force creation even if user has no connected WhatsApp instance',
        )
        parser.add_argument(
            '--all-users',
            action='store_true',
            help='Process all users regardless of WhatsApp connection status',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        specific_user = options.get('user')
        force = options['force']
        all_users = options['all_users']

        if specific_user:
            # Handle single user
            user = User.objects.filter(email=specific_user).first() or \
                   User.objects.filter(username=specific_user).first()
            if not user:
                self.stdout.write(self.style.ERROR(f"❌ User '{specific_user}' not found"))
                return
            users_to_process = [user]
        elif all_users:
            # Get all users (excluding superusers without email)
            users_to_process = User.objects.exclude(email='').exclude(email__isnull=True)
        else:
            # Get all users with connected WhatsApp instances
            connected_instances = UserWhatsAppInstance.objects.filter(status='connected')
            user_ids = connected_instances.values_list('user_id', flat=True).distinct()
            users_to_process = User.objects.filter(id__in=user_ids)

        if not users_to_process:
            self.stdout.write(self.style.WARNING("⚠️  No users with connected WhatsApp instances found."))
            if not force:
                return

        self.stdout.write(f"\n📋 Found {len(users_to_process)} user(s) to process:\n")

        success_count = 0
        partial_count = 0
        failed_count = 0

        for user in users_to_process:
            # Check if user has connected WhatsApp (skip check if --all-users or --force)
            has_connected = UserWhatsAppInstance.objects.filter(
                user=user, status='connected'
            ).exists()
            
            if not has_connected and not force and not all_users:
                self.stdout.write(f"  ⏭️  {user.email or user.username} - no connected WhatsApp, skipping")
                continue

            if dry_run:
                self.stdout.write(f"  🔍 {user.email or user.username} - would create credentials (dry-run)")
                success_count += 1
            else:
                self.stdout.write(f"  🔄 {user.email or user.username} - creating credentials...")
                
                try:
                    success, results = create_n8n_credentials_for_user(user)
                    
                    # Parse results
                    openai_result = next((r for r in results if r[0] == 'openai'), None)
                    evolution_result = next((r for r in results if r[0] == 'evolution'), None)
                    
                    openai_ok = openai_result[1] if openai_result else False
                    evolution_ok = evolution_result[1] if evolution_result else False
                    
                    if openai_ok and evolution_ok:
                        self.stdout.write(self.style.SUCCESS(
                            f"     ✅ Both credentials created successfully"
                        ))
                        success_count += 1
                    elif openai_ok or evolution_ok:
                        self.stdout.write(self.style.WARNING(
                            f"     ⚠️  Partial success: OpenAI={openai_ok}, Evolution={evolution_ok}"
                        ))
                        partial_count += 1
                    else:
                        self.stdout.write(self.style.ERROR(
                            f"     ❌ Failed: {results}"
                        ))
                        failed_count += 1
                        
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f"     ❌ Error: {e}"
                    ))
                    failed_count += 1

        self.stdout.write("")
        if dry_run:
            self.stdout.write(self.style.WARNING(f"DRY RUN: Would process {success_count} user(s)"))
        else:
            self.stdout.write(f"📊 Results:")
            self.stdout.write(self.style.SUCCESS(f"   ✅ Success: {success_count}"))
            if partial_count:
                self.stdout.write(self.style.WARNING(f"   ⚠️  Partial: {partial_count}"))
            if failed_count:
                self.stdout.write(self.style.ERROR(f"   ❌ Failed: {failed_count}"))
        self.stdout.write("")
