# Generated manually for N8NExecutionSnapshot
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('pages', '0004_userwhatsappinstance_hash_key_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='N8NExecutionSnapshot',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('workflow_id', models.CharField(db_index=True, max_length=64)),
                ('execution_id', models.BigIntegerField(unique=True)),
                ('status', models.CharField(blank=True, default='', max_length=64)),
                ('mode', models.CharField(blank=True, default='', max_length=64)),
                ('started_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('stopped_at', models.DateTimeField(blank=True, null=True)),
                ('tokens_total', models.IntegerField(blank=True, null=True)),
                ('tokens_prompt', models.IntegerField(blank=True, null=True)),
                ('tokens_completion', models.IntegerField(blank=True, null=True)),
                ('usage_raw', models.JSONField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='n8n_execution_snapshots', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-started_at', '-execution_id'),
                'indexes': [
                    models.Index(fields=['workflow_id', 'started_at'], name='pages_n8nex_workflo_7f3978_idx'),
                    models.Index(fields=['user', 'started_at'], name='pages_n8nex_user_id_9e4045_idx'),
                ],
            },
        ),
    ]
