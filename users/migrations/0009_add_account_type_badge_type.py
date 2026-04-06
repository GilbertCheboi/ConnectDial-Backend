# Generated manually to add account_type and badge_type to the custom User model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0008_profile_is_bot'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='account_type',
            field=models.CharField(
                choices=[
                    ('fan', 'Fan'),
                    ('news', 'News/Media'),
                    ('organization', 'Club/Organization'),
                ],
                default='fan',
                max_length=15,
            ),
        ),
        migrations.AddField(
            model_name='user',
            name='badge_type',
            field=models.CharField(
                choices=[
                    ('none', 'None'),
                    ('pioneer', 'Pioneer Member'),
                    ('superfan', 'Verified Superfan'),
                    ('official', 'Official Media'),
                    ('verified', 'Verified Personality'),
                ],
                default='none',
                max_length=15,
            ),
        ),
    ]
