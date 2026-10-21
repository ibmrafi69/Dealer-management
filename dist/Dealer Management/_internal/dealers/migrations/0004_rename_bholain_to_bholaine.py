from django.db import migrations


def rename_default_route(apps, schema_editor):
    Route = apps.get_model("dealers", "Route")
    legacy_route = Route.objects.filter(route_name__iexact="Bholain").first()
    canonical_route_exists = Route.objects.filter(route_name__iexact="Bholaine").exists()
    if legacy_route and not canonical_route_exists:
        legacy_route.route_name = "Bholaine"
        legacy_route.save(update_fields=["route_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("dealers", "0003_alter_route_options"),
    ]

    operations = [
        migrations.RunPython(rename_default_route, migrations.RunPython.noop),
    ]
