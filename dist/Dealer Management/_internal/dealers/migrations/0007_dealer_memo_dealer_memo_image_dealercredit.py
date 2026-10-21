from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("dealers", "0006_dealer_credit_fields_and_payment")]

    operations = [
        migrations.AddField(
            model_name="dealer",
            name="memo",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="dealer",
            name="memo_image",
            field=models.FileField(blank=True, null=True, upload_to="dealer_memos/"),
        ),
        migrations.CreateModel(
            name="DealerCredit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("credit_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("dealer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="manual_credits", to="dealers.dealer")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="dealer_credits", to="dealers.group")),
            ],
            options={"ordering": ["credit_date", "created_at", "id"]},
        ),
    ]
