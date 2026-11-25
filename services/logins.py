"""Creates login accounts for every Customer, Mechanic and Staff member that doesn't have one yet."""
import csv
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password

from .models import Customer, Mechanic, Profile

DEMO_PASSWORDS = {'customer': 'customer123', 'mechanic': 'mech123', 'staff': 'staff123'}
STAFF_MEMBERS = [('staff1', 'Komal', 'Arora'), ('staff2', 'Vikram', 'Chopra'), ('staff3', 'Neha', 'Mehta')]


def create_missing_logins():
    """Idempotent: only creates what is missing. Returns {'customer': n, 'mechanic': n, 'staff': n}."""
    User = get_user_model()
    # hash each password once; reusing the hash keeps this fast even for hundreds of accounts
    hashed = {role: make_password(pw) for role, pw in DEMO_PASSWORDS.items()}
    made = {'customer': 0, 'mechanic': 0, 'staff': 0}

    for c in Customer.objects.filter(profile__isnull=True):
        username = f'customer{c.pk}'
        if User.objects.filter(username=username).exists():
            continue
        u = User.objects.create(username=username, first_name=c.name.split()[0], email=c.email,
                                password=hashed['customer'])
        Profile.objects.create(user=u, role='customer', customer=c)
        made['customer'] += 1

    for m in Mechanic.objects.filter(profile__isnull=True):
        username = f'mech{m.pk}'
        if User.objects.filter(username=username).exists():
            continue
        u = User.objects.create(username=username, first_name=m.name.split()[0],
                                password=hashed['mechanic'], is_active=m.is_active)
        Profile.objects.create(user=u, role='mechanic', mechanic=m)
        made['mechanic'] += 1

    for username, first, last in STAFF_MEMBERS:
        if User.objects.filter(username=username).exists():
            continue
        u = User.objects.create(username=username, first_name=first, last_name=last, password=hashed['staff'])
        Profile.objects.create(user=u, role='staff')
        made['staff'] += 1
    return made


def write_logins_csv(path):
    """List of demo logins (role, username, password, name, phone) for the project report / viva."""
    rows = []
    for p in Profile.objects.select_related('user', 'customer', 'mechanic').order_by('role', 'user__id'):
        if p.role == 'customer':
            name, phone = p.customer.name, p.customer.phone
        elif p.role == 'mechanic':
            name, phone = p.mechanic.name, p.mechanic.phone
        else:
            name, phone = f"{p.user.first_name} {p.user.last_name}".strip(), ''
        rows.append((p.role, p.user.username, DEMO_PASSWORDS[p.role], name, phone,
                     'yes' if p.user.is_active else 'no (former employee)'))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['role', 'username', 'password', 'name', 'phone', 'can_log_in'])
        w.writerows(rows)
    return len(rows)
