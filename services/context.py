from .access import HOME, user_role

STAFF_NAV = [
    ("Dashboard", "dashboard", "dashboard"),
    ("Bookings", "booking_list", "booking"),
    ("Customers", "customer_list", "customer"),
    ("Cars", "car_list", "car"),
    ("Payments", "payment_list", "payment"),
]
ACCOUNT = ("My account", "account", "account")
ADMIN_NAV = STAFF_NAV[:4] + [
    ("Services", "service_list", "service"),
    ("Parts", "part_list", "part"),
    ("Mechanics", "mechanic_list", "mechanic"),
    ("Suppliers", "supplier_list", "supplier"),
    ("Payments", "payment_list", "payment"),
    ("Reports", "reports", "reports"),
    ACCOUNT,
]
NAVS = {
    'admin': ADMIN_NAV,
    'staff': STAFF_NAV + [ACCOUNT],
    'customer': [
        ("Home", "portal_home", "portal_home"),
        ("My cars", "portal_cars", "portal_car"),
        ("Book a service", "portal_book_new", "portal_book_new"),
        ("My bookings", "portal_bookings", "portal_booking"),
        ("Payments", "portal_payments", "portal_pay"),
        ("My account", "account", "account"),
    ],
    'mechanic': [
        ("Home", "mech_home", "mech_home"),
        ("My jobs", "mech_jobs", "mech_job"),
        ("My account", "account", "account"),
    ],
}
LABELS = {'admin': 'Admin / Owner', 'staff': 'Staff', 'customer': 'Customer', 'mechanic': 'Mechanic'}


def nav(request):
    role = user_role(request.user)
    return {"nav": NAVS.get(role, []), "role": role, "role_label": LABELS.get(role, ''),
            "home_url": HOME.get(role, 'home')}
