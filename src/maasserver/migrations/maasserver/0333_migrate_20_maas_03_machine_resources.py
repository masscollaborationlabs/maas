# Generated by Django 3.2.12 on 2024-10-03 12:25

from datetime import datetime

from django.db import migrations

from maasserver.enum import NODE_TYPE
from metadataserver.enum import SCRIPT_STATUS


def migrate_20_maas_03_machine_resources_script(apps, schema_editor):
    Script = apps.get_model("maasserver", "Script")
    if not Script.objects.exists():
        # Scripts are generated programmatically for new installations. Nothing to do here.
        return

    Node = apps.get_model("maasserver", "Node")
    ScriptResult = apps.get_model("maasserver", "ScriptResult")

    commissioning_script_name = "20-maas-03-machine-resources"
    script = Script.objects.filter(name=commissioning_script_name).first()
    if not script:
        # If the 20-maas-03-machine-resources is not present there is nothing to do here.
        return

    machines = Node.objects.filter(node_type=NODE_TYPE.MACHINE)

    for machine in machines:
        scriptset = machine.current_commissioning_script_set

        # If the machine never executed the `20-maas-03-machine-resources` commissioning script it means that it was commissioned
        # with MAAS 2.x
        if (
            scriptset
            and scriptset.scriptresult_set
            and not scriptset.scriptresult_set.filter(
                script_name=commissioning_script_name
            ).exists()
        ):
            now = datetime.now()
            ScriptResult.objects.create(
                script=script,
                script_set=scriptset,
                status=SCRIPT_STATUS.SKIPPED,
                script_name=commissioning_script_name,
                created=now,
                updated=now,
                started=now,
                ended=now,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("maasserver", "0332_node_enable_kernel_crash_dump"),
    ]

    operations = [
        migrations.RunPython(migrate_20_maas_03_machine_resources_script),
    ]
