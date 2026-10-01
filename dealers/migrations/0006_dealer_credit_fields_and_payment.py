from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("dealers", "0005_group_alter_dealer_code_alter_route_route_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="dealer",
            name="contact_person",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="dealer",
            name="location",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="dealer",
            name="opening_due",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=14),
        ),
        migrations.AddField(
            model_name="dealer",
            name="route",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="dealers", to="dealers.route"),
        ),
        migrations.CreateModel(
            name="DealerPayment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("payment_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("method", models.CharField(choices=[("CASH", "Cash"), ("BANK", "Bank"), ("MOBILE", "Mobile Banking"), ("OTHER", "Other")], default="CASH", max_length=12)),
                ("reference", models.CharField(blank=True, max_length=120)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("dealer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="dealers.dealer")),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="dealer_payments", to="dealers.group")),
            ],
            options={"ordering": ["payment_date", "created_at", "id"]},
        ),
    ]
