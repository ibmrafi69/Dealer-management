from decimal import Decimal

from django.db import migrations, models


def backfill_shortages(apps, schema_editor):
    PaymentReconciliation = apps.get_model("sales", "PaymentReconciliation")

    for reconciliation in PaymentReconciliation.objects.select_related("transaction").all():
        transaction = reconciliation.transaction
        items = list(transaction.items.all())
        item_damage_product_ids = {item.product_id for item in items if item.damage_quantity}
        unitemized_damage_total = sum(
            (
                damage.value
                for damage in transaction.damages.all()
                if damage.product_id not in item_damage_product_ids
            ),
            Decimal("0"),
        )
        grand_total_sale = sum((item.sale_value for item in items), Decimal("0")) - unitemized_damage_total
        reconciliation.shortage = (
            grand_total_sale
            - reconciliation.cash
            - reconciliation.expenses
            - reconciliation.credit
            - reconciliation.discount
            - reconciliation.others
        ).quantize(Decimal("0.01"))
        reconciliation.save(update_fields=["shortage"])


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0009_backfill_sales_item_snapshots"),
        ("inventory", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="paymentreconciliation",
            name="shortage",
            field=models.DecimalField(decimal_places=2, default=0, editable=False, max_digits=14),
        ),
        migrations.RunPython(backfill_shortages, migrations.RunPython.noop),
    ]
