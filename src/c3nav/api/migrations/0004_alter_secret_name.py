# Generated by Django 4.2.7 on 2023-12-01 19:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_rename_token_logintoken_secret'),
    ]

    operations = [
        migrations.AlterField(
            model_name='secret',
            name='name',
            field=models.CharField(max_length=32, verbose_name='name'),
        ),
    ]