"""Raw-SQL reports. The same queries are shown on the Reports page and exported to docs/queries.sql."""

REPORTS = [
    {
        'title': 'Revenue by service category',
        'desc': 'JOIN across 3 tables + GROUP BY. Which kinds of work earn the most?',
        'sql': """SELECT sc.name AS category,
       COUNT(*)            AS jobs,
       SUM(bs.price)       AS service_revenue
FROM booking_service bs
JOIN service s           ON s.id = bs.service_id
JOIN service_category sc ON sc.id = s.category_id
JOIN booking b           ON b.id = bs.booking_id
WHERE b.status = 'Completed'
GROUP BY sc.name
ORDER BY service_revenue DESC;""",
    },
    {
        'title': 'Top 10 customers by amount paid',
        'desc': 'Four-table JOIN with aggregation and LIMIT. Only confirmed payments count.',
        'sql': """SELECT c.name, c.city, COUNT(DISTINCT b.id) AS bookings, SUM(p.amount) AS total_paid
FROM customer c
JOIN car car     ON car.customer_id = c.id
JOIN booking b   ON b.car_id = car.id
JOIN payment p   ON p.booking_id = b.id AND p.status = 'Confirmed'
GROUP BY c.id
ORDER BY total_paid DESC
LIMIT 10;""",
    },
    {
        'title': 'Mechanic performance',
        'desc': 'LEFT JOIN so mechanics with no jobs still appear; shows average customer rating.',
        'sql': """SELECT m.name,
       COUNT(DISTINCT b.id)          AS completed_jobs,
       ROUND(AVG(f.rating), 2)       AS avg_rating
FROM mechanic m
LEFT JOIN booking b  ON b.mechanic_id = m.id AND b.status = 'Completed'
LEFT JOIN feedback f ON f.booking_id = b.id
GROUP BY m.id
ORDER BY completed_jobs DESC;""",
    },
    {
        'title': 'Outstanding dues (uses the SQL view)',
        'desc': 'Reads from the view vw_booking_balance and filters with a JOIN.',
        'sql': """SELECT v.booking_id, c.name AS customer, car.registration_number,
       v.grand_total, v.paid_total, v.balance_due
FROM vw_booking_balance v
JOIN car car ON car.id = v.car_id
JOIN customer c ON c.id = car.customer_id
WHERE v.status <> 'Cancelled' AND v.balance_due > 0
ORDER BY v.balance_due DESC
LIMIT 15;""",
    },
    {
        'title': 'Parts that need re-ordering',
        'desc': 'Compares two columns of the same row; joins to supplier so you know who to call.',
        'sql': """SELECT p.sku, p.name, p.stock_qty, p.reorder_level, s.name AS supplier, s.phone
FROM part p
JOIN supplier s ON s.id = p.supplier_id
WHERE p.stock_qty <= p.reorder_level
ORDER BY p.stock_qty;""",
    },
    {
        'title': 'Monthly revenue (last 12 months)',
        'desc': 'strftime() + GROUP BY on dates.',
        'sql': """SELECT strftime('%Y-%m', paid_on) AS month,
       COUNT(*)    AS payments,
       SUM(amount) AS collected
FROM payment
WHERE status = 'Confirmed'
GROUP BY month
ORDER BY month DESC
LIMIT 12;""",
    },
    {
        'title': 'Most serviced car brands',
        'desc': 'Subquery-free aggregate over car + booking.',
        'sql': """SELECT car.brand, COUNT(b.id) AS bookings, COUNT(DISTINCT car.id) AS cars
FROM car
JOIN booking b ON b.car_id = car.id
GROUP BY car.brand
ORDER BY bookings DESC;""",
    },
    {
        'title': 'Customers who never booked a service',
        'desc': 'Anti-join using NOT EXISTS.',
        'sql': """SELECT c.id, c.name, c.phone, c.city
FROM customer c
WHERE NOT EXISTS (
    SELECT 1 FROM car JOIN booking b ON b.car_id = car.id WHERE car.customer_id = c.id
)
ORDER BY c.name;""",
    },
    {
        'title': 'Services priced above the average',
        'desc': 'Scalar subquery in WHERE.',
        'sql': """SELECT name, price
FROM service
WHERE price > (SELECT AVG(price) FROM service)
ORDER BY price DESC;""",
    },
]
