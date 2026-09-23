from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0042_remove_student_parent_contact_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="student",
            name="guardians",
        ),
        # Drop the through-table first (it holds the FK to Guardian)
        migrations.DeleteModel(
            name="StudentGuardian",
        ),
        # Drop Guardian model
        migrations.DeleteModel(
            name="Guardian",
        ),
        # Re-add parent contact fields to Student
        migrations.AddField(
            model_name="student",
            name="parent_contact",
            field=models.CharField(default="", max_length=20, verbose_name="Téléphone parent"),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="student",
            name="parent_contact_2",
            field=models.CharField(blank=True, max_length=20, verbose_name="Téléphone parent 2"),
        ),
        migrations.AddField(
            model_name="student",
            name="parent_name",
            field=models.CharField(blank=True, max_length=100, verbose_name="Nom du parent"),
        ),
    ]
