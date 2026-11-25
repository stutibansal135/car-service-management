"""
Fills the database with realistic demo data.

    python manage.py seed_data            # add data (only if the DB is empty)
    python manage.py seed_data --reset    # wipe all CSM tables first, then re-seed

Uses a fixed random seed, so everyone running it gets the same dataset.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from services.logins import create_missing_logins, write_logins_csv
from services.models import (Booking, BookingPart, BookingService, Car, Customer, Feedback,
                             Mechanic, Part, Payment, PaymentBatch, Profile, Service, ServiceCategory, Supplier)

FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karan", "Harpreet", "Gurpreet", "Manpreet", "Jaspreet",
         "Simran", "Navneet", "Amandeep", "Rajveer", "Sukhdeep", "Ishaan", "Kabir", "Dev", "Abhay", "Rami",
         "Priya", "Anjali", "Neha", "Pooja", "Riya", "Sneha", "Kavya", "Tanvi", "Shital", "Nisha",
         "Rahul", "Amit", "Vikram", "Sandeep", "Deepak", "Ankit", "Mohit", "Varun", "Nitin", "Sahil",
         "Meera", "Divya", "Komal", "Ritu", "Swati", "Payal", "Aman", "Lakshay", "Tarun", "Yash"]
LAST = ["Sharma", "Singh", "Gill", "Sidhu", "Kaur", "Verma", "Gupta", "Mehta", "Bansal", "Chopra",
        "Arora", "Kapoor", "Malhotra", "Bhatia", "Grewal", "Dhillon", "Brar", "Sandhu", "Walia", "Khanna",
        "Joshi", "Jain", "Aggarwal", "Thakur", "Saini", "Bajwa", "Randhawa", "Tiwari", "Mittal", "Garg"]
CITIES = [("Ludhiana", "PB10", 38), ("Chandigarh", "CH01", 12), ("Patiala", "PB11", 10), ("Amritsar", "PB02", 9),
          ("Jalandhar", "PB08", 9), ("Mohali", "PB65", 10), ("Bathinda", "PB03", 6), ("Panchkula", "HR03", 6)]
AREAS = ["Model Town", "Sarabha Nagar", "Civil Lines", "BRS Nagar", "Sector 17", "Phase 7", "Urban Estate",
         "Rajpura Road", "Dugri", "Pakhowal Road", "Focal Point", "Green Avenue", "Ranjit Avenue", "Adarsh Nagar"]
COLORS = ["White", "Silver", "Grey", "Black", "Red", "Blue", "Brown", "Orange"]

CARS = {
    "Maruti Suzuki": ["Swift", "Baleno", "Dzire", "Brezza", "WagonR", "Ertiga", "Alto K10", "Fronx"],
    "Hyundai": ["i20", "Creta", "Venue", "Verna", "Grand i10 Nios", "Exter"],
    "Tata": ["Nexon", "Punch", "Harrier", "Altroz", "Tiago", "Safari"],
    "Mahindra": ["Thar", "XUV700", "Scorpio-N", "Bolero", "XUV300"],
    "Honda": ["City", "Amaze", "Elevate"],
    "Toyota": ["Innova Crysta", "Fortuner", "Glanza", "Urban Cruiser Hyryder"],
    "Kia": ["Seltos", "Sonet", "Carens"],
    "Volkswagen": ["Virtus", "Taigun"],
    "Skoda": ["Slavia", "Kushaq"],
    "Renault": ["Kwid", "Kiger"],
}
BRAND_WEIGHTS = [30, 20, 14, 10, 6, 6, 5, 3, 3, 3]

# category -> [(service, price, minutes, description)]
SERVICES = {
    "Routine Maintenance": [
        ("Basic Service", 2499, 120, "Oil and filter change, fluid top-ups, 20-point check."),
        ("Comprehensive Service", 4999, 240, "Full service with brake, suspension and AC inspection."),
        ("Engine Oil & Filter Change", 1899, 60, "Engine oil and oil filter replacement."),
        ("Air Filter Replacement", 699, 30, "Replace engine air filter."),
        ("Coolant Flush", 1299, 60, "Drain and refill radiator coolant."),
    ],
    "Brakes": [
        ("Brake Pad Replacement", 2200, 90, "Replace front or rear brake pads."),
        ("Brake Disc Replacement", 4500, 150, "Replace worn brake discs."),
        ("Brake Fluid Change", 999, 45, "Flush and replace DOT4 brake fluid."),
    ],
    "Tyres & Wheels": [
        ("Wheel Alignment", 899, 45, "Computerised 4-wheel alignment."),
        ("Wheel Balancing", 699, 40, "Balance all four wheels."),
        ("Tyre Rotation", 399, 30, "Rotate tyres to even out wear."),
        ("Puncture Repair", 150, 20, "Tubeless puncture repair."),
        ("Tyre Replacement", 500, 40, "Fitting charges for new tyres."),
    ],
    "Engine & Transmission": [
        ("Engine Diagnostics", 1200, 60, "OBD scan and fault analysis."),
        ("Clutch Plate Replacement", 6500, 300, "Replace clutch plate and pressure plate."),
        ("Timing Belt Replacement", 5500, 240, "Replace timing belt kit."),
        ("Spark Plug Replacement", 1100, 60, "Replace all spark plugs."),
        ("Gearbox Oil Change", 1800, 75, "Replace manual/automatic gearbox oil."),
    ],
    "Electrical & AC": [
        ("AC Gas Refill", 1999, 60, "Evacuate and refill R134a gas."),
        ("AC Compressor Repair", 7500, 240, "Repair or replace AC compressor."),
        ("Battery Replacement", 800, 30, "Battery fitting and terminal cleaning."),
        ("Alternator Repair", 3500, 150, "Repair or replace alternator."),
        ("Headlight Restoration", 1200, 60, "Polish and seal foggy headlights."),
    ],
    "Suspension & Steering": [
        ("Shock Absorber Replacement", 3800, 180, "Replace front or rear shock absorbers."),
        ("Steering Rack Repair", 5200, 240, "Repair steering rack and tie rods."),
        ("Suspension Bush Replacement", 1800, 120, "Replace worn suspension bushes."),
    ],
    "Body & Detailing": [
        ("Full Car Wash", 399, 45, "Exterior wash, vacuum and tyre polish."),
        ("Interior Deep Cleaning", 2499, 180, "Shampoo seats, mats and roof lining."),
        ("Ceramic Coating", 14999, 480, "9H ceramic coating with 2-year warranty."),
        ("Dent & Paint (per panel)", 3500, 300, "Dent removal and repaint of one panel."),
        ("Teflon Polish", 3999, 180, "Teflon paint protection polish."),
    ],
}

SUPPLIERS = [("Sharma Auto Spares", "Ludhiana"), ("Punjab Tyre House", "Ludhiana"),
             ("Northern Lubricants Co.", "Chandigarh"), ("Gill Battery Agency", "Patiala"),
             ("Super Brakes & Clutch", "Jalandhar"), ("Malwa Auto Electricals", "Bathinda"),
             ("Capital Car Accessories", "Chandigarh"), ("Amritsar Genuine Parts Depot", "Amritsar")]

# (sku, name, supplier index, price, starting stock range, reorder level)
PARTS = [
    ("OIL-5W30-1L", "Engine Oil 5W-30 (1 L)", 2, 620, (60, 140), 25),
    ("OIL-FLT", "Oil Filter", 0, 280, (40, 100), 15),
    ("AIR-FLT", "Air Filter", 0, 450, (30, 80), 12),
    ("CAB-FLT", "Cabin AC Filter", 0, 520, (20, 60), 10),
    ("FUEL-FLT", "Fuel Filter", 0, 650, (15, 45), 8),
    ("COOLANT-1L", "Coolant (1 L)", 2, 340, (40, 90), 15),
    ("BRK-FLUID", "Brake Fluid DOT4 (500 ml)", 2, 360, (25, 70), 10),
    ("GBX-OIL-1L", "Gearbox Oil (1 L)", 2, 780, (20, 50), 10),
    ("BRK-PAD-F", "Brake Pad Set (Front)", 4, 1650, (15, 45), 8),
    ("BRK-PAD-R", "Brake Pad Set (Rear)", 4, 1350, (10, 35), 6),
    ("BRK-DISC-F", "Brake Disc (Front, pair)", 4, 3200, (6, 20), 4),
    ("CLUTCH-SET", "Clutch Plate Set", 4, 5200, (4, 14), 3),
    ("SPARK-PLUG", "Spark Plug", 5, 380, (50, 120), 20),
    ("BAT-35AH", "Battery 35 Ah", 3, 4200, (5, 14), 3),
    ("BAT-65AH", "Battery 65 Ah", 3, 6800, (4, 12), 3),
    ("WIPER-BLD", "Wiper Blade (pair)", 6, 540, (15, 50), 8),
    ("BULB-H4", "Headlight Bulb H4", 5, 420, (20, 60), 10),
    ("TIMING-KIT", "Timing Belt Kit", 7, 4300, (4, 12), 3),
    ("SHOCK-F", "Shock Absorber (Front)", 4, 2900, (6, 18), 4),
    ("SHOCK-R", "Shock Absorber (Rear)", 4, 2400, (6, 18), 4),
    ("SUSP-BUSH", "Suspension Bush Set", 4, 950, (10, 30), 6),
    ("AC-GAS-500", "AC Gas R134a (500 g)", 5, 850, (15, 40), 8),
    ("AC-COMP", "AC Compressor", 5, 11500, (2, 6), 2),
    ("ALTERNATOR", "Alternator", 5, 6200, (2, 7), 2),
    ("TYRE-185-65", "Tyre 185/65 R15", 1, 4600, (8, 24), 6),
    ("TYRE-215-60", "Tyre 215/60 R16", 1, 6900, (6, 20), 4),
    ("VALVE-TL", "Tubeless Valve", 1, 60, (80, 200), 30),
    ("SERP-BELT", "Serpentine Belt", 7, 1100, (8, 25), 5),
    ("RAD-HOSE", "Radiator Hose", 7, 760, (8, 25), 5),
    ("HORN-SET", "Horn Set", 6, 680, (8, 25), 5),
]

# service name -> [(part name, quantity)]
SERVICE_PARTS = {
    "Basic Service": [("Engine Oil 5W-30 (1 L)", 4), ("Oil Filter", 1)],
    "Comprehensive Service": [("Engine Oil 5W-30 (1 L)", 4), ("Oil Filter", 1), ("Air Filter", 1),
                              ("Cabin AC Filter", 1)],
    "Engine Oil & Filter Change": [("Engine Oil 5W-30 (1 L)", 4), ("Oil Filter", 1)],
    "Air Filter Replacement": [("Air Filter", 1)],
    "Coolant Flush": [("Coolant (1 L)", 3)],
    "Brake Pad Replacement": [("Brake Pad Set (Front)", 1)],
    "Brake Disc Replacement": [("Brake Disc (Front, pair)", 1), ("Brake Pad Set (Front)", 1)],
    "Brake Fluid Change": [("Brake Fluid DOT4 (500 ml)", 1)],
    "Tyre Replacement": [("Tyre 185/65 R15", 4), ("Tubeless Valve", 4)],
    "Puncture Repair": [("Tubeless Valve", 1)],
    "Clutch Plate Replacement": [("Clutch Plate Set", 1)],
    "Timing Belt Replacement": [("Timing Belt Kit", 1)],
    "Spark Plug Replacement": [("Spark Plug", 4)],
    "Gearbox Oil Change": [("Gearbox Oil (1 L)", 3)],
    "AC Gas Refill": [("AC Gas R134a (500 g)", 1)],
    "AC Compressor Repair": [("AC Compressor", 1)],
    "Battery Replacement": [("Battery 35 Ah", 1)],
    "Alternator Repair": [("Alternator", 1)],
    "Headlight Restoration": [("Headlight Bulb H4", 2)],
    "Shock Absorber Replacement": [("Shock Absorber (Front)", 2)],
    "Suspension Bush Replacement": [("Suspension Bush Set", 1)],
    "Steering Rack Repair": [("Serpentine Belt", 1)],
}

MECHANICS = [("Balwinder Singh", "Engine & Transmission"), ("Harjit Singh", "Engine & Transmission"),
             ("Ramesh Kumar", "Routine Maintenance"), ("Sukhi Gill", "Routine Maintenance"),
             ("Mohan Lal", "Brakes"), ("Jagdev Singh", "Brakes"), ("Pappu Yadav", "Tyres & Wheels"),
             ("Gurmeet Sandhu", "Electrical & AC"), ("Anil Verma", "Electrical & AC"),
             ("Kuldeep Saini", "Suspension & Steering"), ("Satnam Singh", "Body & Detailing"),
             ("Vicky Thakur", "Body & Detailing")]

COMMENTS = ["Quick and clean work, car feels brand new.", "Fair pricing and honest advice.",
            "Delivered on time as promised.", "Staff explained every charge clearly.",
            "Good service but waiting area could be better.", "Took a bit longer than expected.",
            "Excellent work on the AC, cooling is great now.", "Will definitely come back.",
            "Brake noise gone, very happy.", "Pickup and drop was smooth.",
            "Average experience, nothing special.", "Polite staff and spotless wash."]


class Command(BaseCommand):
    help = "Populate the database with realistic demo data."

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete all CSM data before seeding')
        parser.add_argument('--customers', type=int, default=150)
        parser.add_argument('--bookings', type=int, default=700)

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts['reset']:
            get_user_model().objects.all().delete()      # also removes Profiles
            for m in (Profile, Feedback, Payment, PaymentBatch, BookingPart, BookingService, Booking, Part, Supplier,
                      Mechanic, Service, ServiceCategory, Car, Customer):
                m.objects.all().delete()
        elif Customer.objects.exists():
            self.stdout.write(self.style.WARNING("Data already exists. Use --reset to wipe and re-seed."))
            return

        rnd = random.Random(42)
        today = timezone.localdate()

        # ---- services ----
        cats, services = {}, {}
        for cname, items in SERVICES.items():
            cats[cname] = ServiceCategory.objects.create(name=cname)
            for name, price, mins, desc in items:
                services[name] = Service.objects.create(
                    category=cats[cname], name=name, price=price, duration_minutes=mins, description=desc)

        # ---- mechanics ----
        used_phones = set()

        def phone():
            while True:
                p = str(rnd.choice("6789")) + ''.join(rnd.choice("0123456789") for _ in range(9))
                if p not in used_phones:
                    used_phones.add(p)
                    return p

        mechanics = [Mechanic.objects.create(
            name=n, phone=phone(), specialization=cats[c],
            hire_date=today - timedelta(days=rnd.randint(200, 2500)), is_active=True) for n, c in MECHANICS]
        mechanics[-1].is_active = False  # one former employee, for realism
        mechanics[-1].save()
        active_mechanics = [m for m in mechanics if m.is_active]

        # ---- suppliers & parts ----
        suppliers = [Supplier.objects.create(name=n, city=c, phone=phone(),
                                             email=n.split()[0].lower() + "@example.com") for n, c in SUPPLIERS]
        parts = {}
        for sku, name, si, price, (lo, hi), reorder in PARTS:
            parts[name] = Part.objects.create(sku=sku, name=name, supplier=suppliers[si], unit_price=price,
                                              stock_qty=rnd.randint(lo, hi), reorder_level=reorder)

        # ---- customers & cars ----
        city_pool = [c for c in CITIES for _ in range(c[2])]
        brands = list(CARS)
        used_regs, customers, cars = set(), [], []
        for i in range(opts['customers']):
            fn, ln = rnd.choice(FIRST), rnd.choice(LAST)
            city, rto, _ = rnd.choice(city_pool)
            cust = Customer.objects.create(
                name=f"{fn} {ln}", phone=phone(), city=city,
                email=f"{fn.lower()}.{ln.lower()}{rnd.randint(1, 99)}@example.com" if rnd.random() < .85 else "",
                address=f"{rnd.randint(1, 450)}, {rnd.choice(AREAS)}, {city}",
                joined_on=today - timedelta(days=rnd.randint(30, 900)))
            customers.append(cust)
            for _ in range(rnd.choices([1, 2, 3], [60, 33, 7])[0]):
                brand = rnd.choices(brands, BRAND_WEIGHTS)[0]
                while True:
                    reg = f"{rto}{''.join(rnd.choices('ABCDEFGHJKLMNPRSTUVWXYZ', k=2))}{rnd.randint(1000, 9999)}"
                    if reg not in used_regs:
                        used_regs.add(reg)
                        break
                cars.append(Car.objects.create(
                    customer=cust, brand=brand, model=rnd.choice(CARS[brand]),
                    year=rnd.randint(2012, today.year), color=rnd.choice(COLORS), registration_number=reg,
                    fuel_type=rnd.choices(['Petrol', 'Diesel', 'CNG', 'Electric'], [50, 35, 11, 4])[0]))

        # ---- bookings ----
        svc_all = list(services.values())
        svc_weights = [3 if s.price < 2500 else 1 for s in svc_all]
        stats = {'bookings': 0, 'payments': 0, 'feedback': 0}
        awaiting = []      # recently completed jobs with money still owing -> some get a pending UPI payment
        part_list = list(parts.values())

        for _ in range(opts['bookings']):
            car = rnd.choice(cars)
            # ~7% of bookings are "this week" so the dashboard has live jobs
            offset = rnd.randint(-3, 0) if rnd.random() < .07 else rnd.randint(-365, 14)
            d = today + timedelta(days=offset)
            if offset > 0:
                status = Booking.PENDING
            elif offset >= -3:
                status = (rnd.choice([Booking.IN_PROGRESS, Booking.IN_PROGRESS, Booking.COMPLETED, Booking.PENDING])
                          if offset == 0 else rnd.choice([Booking.IN_PROGRESS, Booking.COMPLETED]))
            else:
                status = rnd.choices([Booking.COMPLETED, Booking.CANCELLED], [92, 8])[0]
            chosen = []
            for s in rnd.choices(svc_all, svc_weights, k=rnd.choice([1, 1, 2, 2, 3])):
                if s not in chosen:
                    chosen.append(s)
            # mechanic: prefer someone specialised in the first service
            pool = [m for m in active_mechanics if m.specialization_id == chosen[0].category_id] or active_mechanics
            b = Booking.objects.create(
                car=car, booking_date=d, status=status,
                mechanic=None if (status == Booking.PENDING and rnd.random() < .5) else rnd.choice(pool),
                odometer_km=rnd.randint(5000, 140000) if status != Booking.CANCELLED else None,
                notes=rnd.choice(["", "", "Customer reports vibration at high speed.", "Strange noise from front.",
                                  "Regular periodic service.", "Pickup requested.", "Check AC cooling too."]))
            stats['bookings'] += 1
            if status == Booking.CANCELLED:
                continue
            for s in chosen:
                BookingService.objects.create(booking=b, service=s, price=s.price)
            if status != Booking.PENDING:  # parts are issued once work starts
                wanted = {}
                for s in chosen:
                    for pname, qty in SERVICE_PARTS.get(s.name, []):
                        wanted[pname] = wanted.get(pname, 0) + qty
                for pname, qty in wanted.items():
                    p = parts[pname]
                    if p.stock_qty >= qty:
                        BookingPart.objects.create(booking=b, part=p, quantity=qty, unit_price=p.unit_price)
                        p.stock_qty -= qty
                        p.save(update_fields=['stock_qty'])
            total = b.total
            if total == 0:
                continue
            # payments
            if status == Booking.COMPLETED:
                outcome = rnd.choices(['full', 'two', 'partial', 'none'], [68, 14, 10, 8])[0]
                if offset > -10:
                    outcome = rnd.choice(['full', 'partial', 'none'])
            elif status == Booking.IN_PROGRESS:
                outcome = rnd.choice(['advance', 'none'])
            else:
                outcome = 'none'
            amounts = {
                'full': [total], 'none': [],
                'two': [round(total * Decimal('0.4')), None],
                'partial': [round(total * Decimal(rnd.choice(['0.3', '0.5', '0.7'])))],
                'advance': [round(total * Decimal('0.3'))],
            }[outcome]
            paid = Decimal('0')
            for amt in amounts:
                if amt is None:
                    amt = total - paid
                amt = Decimal(amt)
                if amt <= 0:
                    continue
                method = rnd.choices(['UPI', 'Cash', 'Card', 'Net Banking'], [45, 20, 25, 10])[0]
                pdate = min(today, d + timedelta(days=rnd.randint(0, 3)))
                Payment.objects.create(
                    booking=b, amount=amt, method=method, paid_on=pdate,
                    reference='' if method == 'Cash' else f"TXN{rnd.randint(10**9, 10**10 - 1)}")
                paid += amt
                stats['payments'] += 1
            if status == Booking.COMPLETED and paid < total and offset > -45:
                awaiting.append((b, total - paid))
            if status == Booking.COMPLETED and rnd.random() < .55:
                Feedback.objects.create(booking=b, rating=rnd.choices([1, 2, 3, 4, 5], [2, 4, 14, 36, 44])[0],
                                        comment=rnd.choice(COMMENTS))
                stats['feedback'] += 1

        # ---- a few customers have paid by UPI and are waiting for the workshop to verify (staff dashboard demo) ----
        used_utr = set()
        by_customer = {}
        for b, remaining in awaiting:
            by_customer.setdefault(b.car.customer_id, []).append((b, remaining))
        # prefer a customer who owes on two invoices, so the "paid together" case shows up in the demo data
        groups = sorted(by_customer.values(), key=lambda g: -len(g))
        for group in groups[:6]:
            group = group[:2]
            utr = str(rnd.randint(10**11, 10**12 - 1))
            while utr in used_utr:
                utr = str(rnd.randint(10**11, 10**12 - 1))
            used_utr.add(utr)
            day = today - timedelta(days=rnd.randint(0, 2))
            batch = PaymentBatch.objects.create(customer_id=group[0][0].car.customer_id, reference=utr,
                                                total_amount=sum(r for _, r in group), created_on=day)
            for b, remaining in group:
                Payment.objects.create(booking=b, amount=remaining, method='UPI', reference=utr, paid_on=day,
                                       status=Payment.PENDING, batch=batch)
                stats['payments'] += 1

        # ---- restocking: most parts were re-ordered during the year, a few are genuinely low ----
        for p in Part.objects.all():
            if p.stock_qty <= p.reorder_level and rnd.random() < .75:
                p.stock_qty = p.reorder_level * rnd.randint(2, 6)
                p.save(update_fields=['stock_qty'])

        for p in rnd.sample(list(Part.objects.all()), 5):   # a few genuinely low / out of stock
            p.stock_qty = rnd.choice([0, 1, 2, p.reorder_level])
            p.save(update_fields=['stock_qty'])

        # ---- logins: the owner account + one login for every customer, mechanic and staff member ----
        User = get_user_model()
        User.objects.create(username='admin', email='admin@example.com', password=make_password('admin123'),
                            is_staff=True, is_superuser=True)
        made = create_missing_logins()
        write_logins_csv(settings.BASE_DIR.parent / 'docs' / 'logins.csv')

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {len(customers)} customers, {len(cars)} cars, {len(svc_all)} services, "
            f"{len(mechanics)} mechanics, {len(suppliers)} suppliers, {len(parts)} parts, "
            f"{stats['bookings']} bookings, {stats['payments']} payments, {stats['feedback']} feedback.\n"
            f"Logins created: {made['customer']} customers, {made['mechanic']} mechanics, {made['staff']} staff + admin.\n"
            f"  admin / admin123    staff1..3 / staff123    mech1..{len(active_mechanics)} / mech123 "
            f"(mech{len(mechanics)} is a former employee, disabled)    "
            f"customer1..{len(customers)} / customer123\n"
            f"Full list: docs/logins.csv"))
