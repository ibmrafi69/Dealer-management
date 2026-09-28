from django.db import migrations


def backfill_history_snapshots(apps, schema_editor):
    SalesTransaction = apps.get_model("sales", "SalesTransaction")
    SalesItem = apps.get_model("sales", "SalesItem")
    Damage = apps.get_model("inventory", "Damage")

    for transaction in SalesTransaction.objects.select_related("route").all():
        if transaction.route_id and not transaction.route_day:
            transaction.route_day = transaction.route.weekday
            transaction.save(update_fields=["route_day"])
        for item in SalesItem.objects.filter(transaction_id=transaction.pk):
            damages = Damage.objects.filter(related_transaction_id=transaction.pk, product_id=item.product_id)
            damage_quantity = sum((damage.quantity for damage in damages), 0)
            damage_value = sum((damage.value for damage in damages), 0)
            if damage_quantity or damage_value:
                item.damage_quantity = damage_quantity
                item.damage_value = damage_value
                item.save(update_fields=["damage_quantity", "damage_value"])


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0007_salesitem_damage_quantity_salesitem_damage_value_and_more"),
        ("inventory", "0001_initial"),
    ]

    operations = [migrations.RunPython(backfill_history_snapshots, migrations.RunPython.noop)]
