# Generated by Django 4.2.7 on 2023-12-25 21:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapdata', '0097_longer_import_tag'),
    ]

    operations = [
        migrations.AddField(
            model_name='report',
            name='import_tag',
            field=models.CharField(blank=True, max_length=256, null=True, verbose_name='import tag'),
        ),
    ]
