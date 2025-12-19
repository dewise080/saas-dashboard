from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

import magic_notifier.settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='Notification',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('recipient_object_id', models.PositiveBigIntegerField(blank=True, null=True)),
                ('recipient_content_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype')),
                ('subject', models.CharField(blank=True, max_length=255, null=True)),
                ('text', models.TextField()),
                ('type', models.CharField(max_length=30)),
                ('sub_type', models.CharField(blank=True, max_length=30, null=True)),
                ('link', models.CharField(max_length=255, verbose_name='The link associated')),
                ('image', models.ImageField(blank=True, null=True, upload_to='notifications')),
                ('is_visible', models.BooleanField(default=True)),
                ('is_encrypted', models.BooleanField(default=False)),
                ('actions', models.JSONField(default=dict)),
                ('data', models.JSONField(default=dict)),
                ('read', models.DateTimeField(blank=True, null=True)),
                ('sent', models.DateTimeField(auto_now_add=True)),
                ('expires', models.DateTimeField(blank=True, null=True)),
                ('mode', models.CharField(choices=magic_notifier.settings.NOTIFIER_AVAILABLE_MODES, default=magic_notifier.settings.NOTIFIER_DEFAULT_MODE, max_length=10)),
                ('masked', models.BooleanField(default=False)),
                ('inited_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='magic_notifications_inited', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='NotifyProfile',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('phone_number', models.CharField(blank=True, max_length=20, null=True)),
                ('current_channel', models.CharField(blank=True, max_length=255, null=True)),
                ('recipient_object_id', models.PositiveBigIntegerField(blank=True, null=True)),
                ('recipient_content_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype')),
            ],
        ),
    ]
