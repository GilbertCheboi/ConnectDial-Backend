from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE users_user DROP COLUMN IF EXISTS two_fa_enabled;",
            reverse_sql="ALTER TABLE users_user ADD COLUMN IF NOT EXISTS two_fa_enabled boolean NOT NULL DEFAULT false;",
        ),
    ]
