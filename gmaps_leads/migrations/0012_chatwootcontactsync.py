from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('gmaps_leads', '0011_deduplicate_leads'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatwootContactSync',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chatwoot_contact_id', models.IntegerField(blank=True, null=True)),
                ('chatwoot_inbox_id', models.IntegerField(blank=True, null=True)),
                ('source_identifier', models.CharField(blank=True, help_text='Phone or email used to create the contact', max_length=255, null=True)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('synced', 'Synced'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('last_error', models.TextField(blank=True, null=True)),
                ('last_synced_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('lead', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='chatwoot_sync', to='gmaps_leads.gmapslead')),
            ],
            options={
                'verbose_name': 'Chatwoot Contact Sync',
                'verbose_name_plural': 'Chatwoot Contact Syncs',
                'ordering': ['-updated_at'],
            },
        ),
    ]
