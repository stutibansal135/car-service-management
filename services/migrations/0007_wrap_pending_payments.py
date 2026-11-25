from django.db import migrations


def wrap_pending(apps, schema_editor):
    """Payments already waiting for verification become one-invoice batches, so staff verify them the new way."""
    Payment = apps.get_model('services', 'Payment')
    Batch = apps.get_model('services', 'PaymentBatch')
    for p in Payment.objects.filter(status='Pending', method='UPI', batch__isnull=True).select_related('booking__car'):
        b = Batch.objects.create(customer_id=p.booking.car.customer_id, reference=p.reference,
                                 total_amount=p.amount, status='Pending', created_on=p.paid_on)
        p.batch = b
        p.save(update_fields=['batch'])


class Migration(migrations.Migration):
    dependencies = [('services', '0006_payment_batch')]
    operations = [migrations.RunPython(wrap_pending, migrations.RunPython.noop)]
