from django.db import migrations

# Plain SQL views (good to show in a DBMS viva). The app's reports page queries them directly.
CREATE = """
CREATE VIEW vw_booking_totals AS
SELECT b.id AS booking_id,
       b.status,
       b.booking_date,
       b.car_id,
       b.mechanic_id,
       COALESCE((SELECT SUM(bs.price) FROM booking_service bs WHERE bs.booking_id = b.id), 0)            AS services_total,
       COALESCE((SELECT SUM(bp.quantity * bp.unit_price) FROM booking_part bp WHERE bp.booking_id = b.id), 0) AS parts_total,
       COALESCE((SELECT SUM(p.amount) FROM payment p WHERE p.booking_id = b.id), 0)                      AS paid_total
FROM booking b;
"""

CREATE2 = """
CREATE VIEW vw_booking_balance AS
SELECT booking_id, status, booking_date, car_id, mechanic_id,
       services_total, parts_total, paid_total,
       ROUND(services_total + parts_total, 2)               AS grand_total,
       ROUND(services_total + parts_total - paid_total, 2)  AS balance_due
FROM vw_booking_totals;
"""


class Migration(migrations.Migration):
    dependencies = [('services', '0001_initial')]
    operations = [
        migrations.RunSQL(CREATE, 'DROP VIEW IF EXISTS vw_booking_totals;'),
        migrations.RunSQL(CREATE2, 'DROP VIEW IF EXISTS vw_booking_balance;'),
    ]
