"""Preserve message event identities while adding their native foreign key."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0003_outgoingmessage_chat_id"),
        ("payments", "0002_paymentdecisionevent"),
    ]

    operations = [
        migrations.RenameField(
            model_name="outgoingmessage", old_name="source_event_id", new_name="source_event"
        ),
        migrations.AlterField(
            model_name="outgoingmessage",
            name="source_event",
            field=models.OneToOneField(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                to="payments.paymentdecisionevent",
            ),
        ),
        migrations.CreateModel(
            name="InvoiceConversation",
            fields=[
                (
                    "invoice",
                    models.OneToOneField(
                        primary_key=True,
                        serialize=False,
                        on_delete=django.db.models.deletion.PROTECT,
                        to="payments.invoice",
                    ),
                ),
                (
                    "event",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="bots.telegraminbox"
                    ),
                ),
            ],
        ),
    ]
