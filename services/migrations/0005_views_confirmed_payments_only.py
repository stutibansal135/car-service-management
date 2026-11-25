from django.db import migrations

# Rebuild the two SQL views so that only CONFIRMED payments count as paid.
DROP = "DROP VIEW IF EXISTS vw_booking_balance; DROP VIEW IF EXISTS vw_booking_totals;"

def make(confirmed_only):
    cond = " AND p.status = 'Confirmed'" if confirmed_only else ""
    return f"""
CREATE VIEW vw_booking_totals AS
SELECT b.id AS booking_id, b.status, b.booking_date, b.car_id, b.mechanic_id,
       COALESCE((SELECT SUM(bs.price) FROM booking_service bs WHERE bs.booking_id = b.id), 0) AS services_total,
       COALESCE((SELECT SUM(bp.quantity * bp.unit_price) FROM booking_part bp WHERE bp.booking_id = b.id), 0) AS parts_total,
       COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.booking_id = b.id{cond}), 0) AS paid_total
FROM booking b;
CREATE VIEW vw_booking_balance AS
SELECT booking_id, status, booking_date, car_id, mechanic_id,
       services_total, parts_total, paid_total,
       ROUND(services_total + parts_total, 2)              AS grand_total,
       ROUND(services_total + parts_total - paid_total, 2) AS balance_due
FROM vw_booking_totals;
"""


class Migration(migrations.Migration):
    dependencies = [('services', '0004_payment_status')]
    operations = [
        migrations.RunSQL(DROP + make(True), DROP + make(False)),
    ]
