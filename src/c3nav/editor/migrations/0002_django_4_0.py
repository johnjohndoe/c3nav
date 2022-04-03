# Generated by Django 4.0.3 on 2022-04-03 17:32

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('contenttypes', '0002_remove_content_type_name'),
        ('editor', '0001_squashed_2018'),
    ]

    operations = [
        migrations.AlterField(
            model_name='changedobject',
            name='changeset',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='editor.changeset', verbose_name='Change Set'),
        ),
        migrations.AlterField(
            model_name='changedobject',
            name='content_type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='contenttypes.contenttype'),
        ),
        migrations.AlterField(
            model_name='changedobject',
            name='m2m_added',
            field=models.JSONField(default=dict, verbose_name='added m2m values'),
        ),
        migrations.AlterField(
            model_name='changedobject',
            name='m2m_removed',
            field=models.JSONField(default=dict, verbose_name='removed m2m values'),
        ),
        migrations.AlterField(
            model_name='changedobject',
            name='updated_fields',
            field=models.JSONField(default=dict, verbose_name='updated fields'),
        ),
        migrations.AlterField(
            model_name='changeset',
            name='author',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL, verbose_name='Author'),
        ),
    ]
