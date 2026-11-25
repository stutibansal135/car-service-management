from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (Booking, BookingPart, BookingService, Car, Customer, Mechanic, Part, Payment,
                     PaymentBatch, Profile, Service, ServiceCategory, Supplier)

User = get_user_model()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])   # fast tests
class Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', password='x')
        staff = User.objects.create_user('desk', password='x')
        Profile.objects.create(user=staff, role='staff')

        self.cust = Customer.objects.create(name='A Sharma', phone='9876543210')
        self.other = Customer.objects.create(name='B Singh', phone='9876543299')
        self.cu = User.objects.create_user('cust', password='x')
        Profile.objects.create(user=self.cu, role='customer', customer=self.cust)
        ou = User.objects.create_user('cust2', password='x')
        Profile.objects.create(user=ou, role='customer', customer=self.other)

        self.car = Car.objects.create(customer=self.cust, brand='Tata', model='Nexon', year=2020,
                                      registration_number='PB10AB1234')
        self.other_car = Car.objects.create(customer=self.other, brand='Kia', model='Seltos', year=2021,
                                            registration_number='PB10ZZ9999')
        cat = ServiceCategory.objects.create(name='Routine')
        self.svc = Service.objects.create(category=cat, name='Basic', price=1000, duration_minutes=60)
        sup = Supplier.objects.create(name='S', phone='9876543211', city='X')
        self.part = Part.objects.create(sku='P1', name='Oil', supplier=sup, unit_price=200, stock_qty=5)

        self.mech = Mechanic.objects.create(name='M One', phone='9876543212')
        self.mech2 = Mechanic.objects.create(name='M Two', phone='9876543213')
        self.mu = User.objects.create_user('mech', password='x')
        Profile.objects.create(user=self.mu, role='mechanic', mechanic=self.mech)

        self.b = Booking.objects.create(car=self.car, mechanic=self.mech, booking_date=date.today())
        self.ob = Booking.objects.create(car=self.other_car, mechanic=self.mech2, booking_date=date.today())

    def login(self, name):
        self.client.logout()
        self.assertTrue(self.client.login(username=name, password='x'))

    def post(self, url_name, /, *args, **data):
        return self.client.post(reverse(url_name, args=args), data, follow=True)

    def get(self, url_name, /, *args):
        return self.client.get(reverse(url_name, args=args))


class StaffFlowTests(Base):
    def setUp(self):
        super().setUp()
        self.login('boss')

    def test_totals_stock_and_payment_rules(self):
        self.post('booking_add_service', self.b.pk, service=self.svc.pk)
        self.post('booking_add_part', self.b.pk, part=self.part.pk, quantity=3)
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, 2)
        self.assertEqual(self.b.total, Decimal('1600'))
        self.post('booking_add_part', self.b.pk, part=self.part.pk, quantity=9)   # more than stock
        self.assertEqual(BookingPart.objects.count(), 1)
        self.post('booking_add_payment', self.b.pk, amount='2000', method='UPI', paid_on=date.today())
        self.assertEqual(Payment.objects.count(), 0)                                # overpayment
        self.post('booking_add_payment', self.b.pk, amount='600', method='UPI', paid_on=date.today())
        self.assertEqual(self.b.payment_status, 'Partial')
        self.post('booking_set_status', self.b.pk, status='Cancelled')
        self.part.refresh_from_db()
        self.assertEqual(self.part.stock_qty, 5)                                    # stock restored

    def test_workflow_rules(self):
        self.b.mechanic = None
        self.b.save()
        self.post('booking_set_status', self.b.pk, status='In Progress')
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'Pending')           # needs a mechanic
        self.b.mechanic = self.mech
        self.b.save()
        self.post('booking_set_status', self.b.pk, status='Completed')
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'Pending')           # can't skip a step

    def test_db_constraints(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Car.objects.create(customer=self.cust, brand='X', model='Y', year=2020, registration_number='PB10AB1234')
        with self.assertRaises(IntegrityError), transaction.atomic():   # customer login must point at a customer
            Profile.objects.create(user=User.objects.create_user('bad', password='x'), role='customer')

    def test_every_staff_page_loads(self):
        BookingService.objects.create(booking=self.b, service=self.svc, price=1000)
        for u in ['dashboard', 'reports', 'customer_list', 'car_list', 'service_list', 'mechanic_list',
                  'supplier_list', 'part_list', 'booking_list', 'payment_list', 'customer_add', 'car_add',
                  'service_add', 'mechanic_add', 'supplier_add', 'part_add', 'booking_add']:
            self.assertEqual(self.get(u).status_code, 200, u)
        for u, a in [('customer_detail', self.cust.pk), ('booking_detail', self.b.pk), ('invoice', self.b.pk),
                     ('customer_edit', self.cust.pk), ('car_edit', self.car.pk), ('booking_edit', self.b.pk),
                     ('customer_delete', self.cust.pk)]:
            self.assertEqual(self.get(u, a).status_code, 200, u)

    def test_protected_delete_keeps_record(self):
        self.post('customer_delete', self.cust.pk)
        self.assertTrue(Customer.objects.filter(pk=self.cust.pk).exists())


class AccessControlTests(Base):
    def test_anonymous_redirected_to_login(self):
        for u in ['dashboard', 'portal_home', 'mech_home', 'customer_list']:
            r = self.get(u)
            self.assertEqual(r.status_code, 302, u)
            self.assertIn('/login/', r['Location'])
        self.assertEqual(self.get('home').status_code, 200)
        self.assertEqual(self.get('about').status_code, 200)
        self.assertEqual(self.get('track').status_code, 200)

    def test_each_role_lands_on_its_own_home(self):
        for name, target in [('boss', 'dashboard'), ('desk', 'dashboard'), ('cust', 'portal_home'),
                             ('mech', 'mech_home')]:
            self.login(name)
            self.assertRedirects(self.get('after_login'), reverse(target), fetch_redirect_response=False)

    def test_customer_cannot_enter_staff_or_mechanic_areas(self):
        self.login('cust')
        for u in ['dashboard', 'customer_list', 'booking_list', 'reports', 'payment_list', 'mech_home', 'part_list']:
            self.assertEqual(self.get(u).status_code, 302, u)

    def test_mechanic_cannot_enter_other_areas(self):
        self.login('mech')
        for u in ['dashboard', 'customer_list', 'portal_home', 'booking_list', 'reports']:
            self.assertEqual(self.get(u).status_code, 302, u)

    def test_staff_cannot_use_admin_only_pages_or_delete(self):
        self.login('desk')
        for u in ['reports', 'service_list', 'mechanic_list', 'supplier_list', 'part_list']:
            self.assertEqual(self.get(u).status_code, 302, u)
        for u in ['dashboard', 'booking_list', 'customer_list', 'payment_list']:
            self.assertEqual(self.get(u).status_code, 200, u)
        self.assertEqual(self.get('customer_delete', self.cust.pk).status_code, 302)

    def test_account_without_role_is_logged_out(self):
        User.objects.create_user('norole', password='x')
        self.login('norole')
        r = self.get('after_login')
        self.assertRedirects(r, reverse('home'), fetch_redirect_response=False)
        self.assertEqual(self.get('dashboard').status_code, 302)   # was logged out


class CustomerPortalTests(Base):
    def setUp(self):
        super().setUp()
        self.login('cust')

    def test_pages_load(self):
        BookingService.objects.create(booking=self.b, service=self.svc, price=1000)
        for u in ['portal_home', 'portal_cars', 'portal_car_add', 'portal_book_new', 'portal_bookings',
                  'portal_payments', 'account']:
            self.assertEqual(self.get(u).status_code, 200, u)
        for u, a in [('portal_booking_detail', self.b.pk), ('portal_invoice', self.b.pk),
                     ('portal_car_edit', self.car.pk)]:
            self.assertEqual(self.get(u, a).status_code, 200, u)

    def test_cannot_see_other_customers_data(self):
        self.assertEqual(self.get('portal_booking_detail', self.ob.pk).status_code, 404)
        self.assertEqual(self.get('portal_invoice', self.ob.pk).status_code, 404)
        self.assertEqual(self.get('portal_car_edit', self.other_car.pk).status_code, 404)
        self.assertEqual(self.post('portal_booking_pay', self.ob.pk, amount='10', method='UPI').status_code, 404)
        self.assertNotContains(self.get('portal_bookings'), 'PB10ZZ9999')
        self.assertNotContains(self.get('portal_cars'), 'PB10ZZ9999')

    def test_book_service_creates_pending_booking_with_snapshot_price(self):
        r = self.post('portal_book_new', car=self.car.pk, booking_date=date.today() + timedelta(days=2),
                      services=[self.svc.pk], notes='noise')
        b = Booking.objects.latest('id')
        self.assertEqual((b.car, b.status, b.mechanic), (self.car, 'Pending', None))
        self.assertEqual(b.total, Decimal('1000'))
        self.assertContains(r, 'Booking requested')

    def test_cannot_book_for_someone_elses_car_or_past_date_or_no_service(self):
        n = Booking.objects.count()
        self.post('portal_book_new', car=self.other_car.pk, booking_date=date.today(), services=[self.svc.pk])
        self.post('portal_book_new', car=self.car.pk, booking_date=date.today() - timedelta(days=1), services=[self.svc.pk])
        self.post('portal_book_new', car=self.car.pk, booking_date=date.today())
        self.assertEqual(Booking.objects.count(), n)

    def test_add_car_and_duplicate_reg(self):
        self.post('portal_car_add', registration_number='pb 10 xy 5555', brand='Honda', model='City',
                  year=2019, fuel_type='Petrol', color='Red')
        c = Car.objects.get(registration_number='PB10XY5555')
        self.assertEqual(c.customer, self.cust)
        self.post('portal_car_add', registration_number='PB10XY5555', brand='Honda', model='City',
                  year=2019, fuel_type='Petrol')
        self.assertEqual(Car.objects.filter(registration_number='PB10XY5555').count(), 1)

    def test_pay_online_demo_and_overpay(self):
        BookingService.objects.create(booking=self.b, service=self.svc, price=1000)
        self.post('portal_booking_pay', self.b.pk, amount='5000', method='Card')
        self.assertEqual(Payment.objects.count(), 0)
        self.post('portal_booking_pay', self.b.pk, amount='400', method='Net Banking')
        self.post('portal_booking_pay', self.b.pk, amount='600', method='Card')
        self.assertEqual(self.b.payment_status, 'Paid')
        self.post('portal_booking_pay', self.b.pk, amount='1', method='Card')       # already paid
        self.post('portal_booking_pay', self.b.pk, amount='1', method='UPI')        # UPI isn't a demo method
        self.assertEqual(Payment.objects.count(), 2)

    def test_cancel_only_while_pending_and_restores_stock(self):
        BookingPart.objects.create(booking=self.b, part=self.part, quantity=2, unit_price=200)
        Part.objects.filter(pk=self.part.pk).update(stock_qty=3)
        self.post('portal_booking_cancel', self.b.pk)
        self.b.refresh_from_db(); self.part.refresh_from_db()
        self.assertEqual((self.b.status, self.part.stock_qty), ('Cancelled', 5))
        self.b.status = 'In Progress'; self.b.save()
        self.post('portal_booking_cancel', self.b.pk)
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'In Progress')

    def test_feedback_only_when_completed(self):
        self.post('portal_booking_feedback', self.b.pk, rating=5, comment='ok')
        self.assertFalse(hasattr(Booking.objects.get(pk=self.b.pk), 'feedback'))
        self.b.status = 'Completed'; self.b.save()
        self.post('portal_booking_feedback', self.b.pk, rating=5, comment='great')
        self.assertEqual(Booking.objects.get(pk=self.b.pk).feedback.rating, 5)

    def test_signup_creates_customer_login(self):
        self.client.logout()
        r = self.post('signup', name='New Person', phone='9123456780', email='n@x.com', username='newbie',
                      password='Sup3rS3cret!x', confirm_password='Sup3rS3cret!x')
        u = User.objects.get(username='newbie')
        self.assertEqual(u.profile.role, 'customer')
        self.assertEqual(u.profile.customer.phone, '9123456780')
        self.assertContains(r, 'Hello, New Person')
        self.client.logout()
        self.post('signup', name='Dup', phone='9123456780', username='dup', password='Sup3rS3cret!x',
                  confirm_password='Sup3rS3cret!x')
        self.assertFalse(User.objects.filter(username='dup').exists())            # phone already used
        self.post('signup', name='Weak', phone='9123456781', username='weak', password='123', confirm_password='123')
        self.assertFalse(User.objects.filter(username='weak').exists())


class MechanicPortalTests(Base):
    def setUp(self):
        super().setUp()
        BookingService.objects.create(booking=self.b, service=self.svc, price=1000)
        BookingService.objects.create(booking=self.ob, service=self.svc, price=1000)
        self.login('mech')

    def test_pages_load_and_only_own_jobs(self):
        self.assertEqual(self.get('mech_home').status_code, 200)
        r = self.get('mech_jobs')
        self.assertContains(r, 'PB10AB1234')
        self.assertNotContains(r, 'PB10ZZ9999')
        self.assertEqual(self.get('mech_job_detail', self.b.pk).status_code, 200)
        self.assertEqual(self.get('mech_job_detail', self.ob.pk).status_code, 404)
        self.assertEqual(self.post('mech_job_status', self.ob.pk, status='In Progress').status_code, 404)

    def test_job_flow_start_part_note_complete(self):
        self.post('mech_job_status', self.b.pk, status='In Progress')
        self.post('mech_job_add_part', self.b.pk, part=self.part.pk, quantity=2)
        self.post('mech_job_note', self.b.pk, note='Replaced filter')
        self.post('mech_job_status', self.b.pk, status='Completed')
        self.b.refresh_from_db(); self.part.refresh_from_db()
        self.assertEqual(self.b.status, 'Completed')
        self.assertEqual(self.part.stock_qty, 3)
        self.assertIn('Replaced filter', self.b.notes)
        self.post('mech_job_add_part', self.b.pk, part=self.part.pk, quantity=1)    # closed job
        self.assertEqual(BookingPart.objects.filter(booking=self.b).count(), 1)

    def test_mechanic_cannot_cancel_or_skip_steps(self):
        self.post('mech_job_status', self.b.pk, status='Cancelled')
        self.post('mech_job_status', self.b.pk, status='Completed')                 # still Pending
        self.b.refresh_from_db()
        self.assertEqual(self.b.status, 'Pending')

    def test_mechanic_never_sees_money(self):
        r = self.get('mech_job_detail', self.b.pk)
        self.assertNotContains(r, 'Rs ')


class BulkLoginTests(Base):
    def test_create_logins_for_everyone_and_is_repeatable(self):
        gone = Mechanic.objects.create(name='Old Timer', phone='9876543214', is_active=False)
        call_command('create_logins', csv='/tmp/logins_test.csv', verbosity=0)
        # every customer and mechanic now has a profile, plus the staff accounts
        self.assertFalse(Customer.objects.filter(profile__isnull=True).exists())
        self.assertFalse(Mechanic.objects.filter(profile__isnull=True).exists())
        self.assertEqual(Profile.objects.filter(role='staff', user__username__startswith='staff').count(), 3)
        n = User.objects.count()
        call_command('create_logins', csv='/tmp/logins_test.csv', verbosity=0)     # second run adds nothing
        self.assertEqual(User.objects.count(), n)
        # a seeded customer can really log in and lands in the portal
        c = Customer.objects.get(pk=self.other.pk)
        self.client.logout()
        self.assertTrue(User.objects.get(username='cust2').profile.customer == c)  # existing login untouched
        newc = Customer.objects.create(name='Late Joiner', phone='9000000001')
        call_command('create_logins', csv='/tmp/logins_test.csv', verbosity=0)
        user = User.objects.get(username=f'customer{newc.pk}')
        user.set_password('x'); user.save()
        self.assertTrue(self.client.login(username=user.username, password='x'))
        self.assertEqual(self.get('portal_home').status_code, 200)
        # former employee: account exists but is disabled
        self.assertFalse(User.objects.get(username=f'mech{gone.pk}').is_active)

    def test_inactive_mechanic_with_active_account_still_locked_out(self):
        self.mech.is_active = False
        self.mech.save()
        self.login('mech')
        self.assertEqual(self.get('mech_home').status_code, 302)


class UpiPaymentTests(Base):
    UTR = '412345678901'

    def setUp(self):
        super().setUp()
        BookingService.objects.create(booking=self.b, service=self.svc, price=1000)     # invoice total Rs 1000

    def submit(self, amount='1000', utr=None):
        return self.post('portal_pay_upi', self.b.pk, amount=amount, utr=utr or self.UTR)

    def test_checkout_page_has_upi_link_and_qr(self):
        self.login('cust')
        r = self.client.get(reverse('portal_pay_checkout', args=[self.b.pk]) + '?amount=400')
        self.assertContains(r, 'upi://pay?pa=')
        self.assertContains(r, 'am=400.00')
        self.assertContains(r, '<svg')                       # QR code rendered on the server
        # out-of-range amounts fall back to the payable amount
        r = self.client.get(reverse('portal_pay_checkout', args=[self.b.pk]) + '?amount=99999')
        self.assertContains(r, 'am=1000.00')

    def test_submitted_upi_payment_is_pending_and_not_counted_as_paid(self):
        self.login('cust')
        self.submit('1000')
        p = Payment.objects.get()
        self.assertEqual((p.status, p.method, p.reference), ('Pending', 'UPI', self.UTR))
        self.assertEqual(self.b.paid_total, 0)
        self.assertEqual(self.b.pending_total, Decimal('1000'))
        self.assertEqual(self.b.payment_status, 'Verifying')
        self.assertEqual(self.b.payable, 0)
        # nothing left to pay now: cannot submit again, nor pay by card, nor via staff form
        self.submit('1', utr='999999999999')
        self.post('portal_booking_pay', self.b.pk, amount='1', method='Card')
        self.assertEqual(Payment.objects.count(), 1)

    def test_sql_view_ignores_pending_payments(self):
        from django.db import connection
        self.login('cust')
        self.submit('1000')
        with connection.cursor() as c:
            c.execute("SELECT paid_total, balance_due FROM vw_booking_balance WHERE booking_id=%s", [self.b.pk])
            self.assertEqual(c.fetchone(), (0, 1000))

    def test_utr_validation_and_duplicates(self):
        self.login('cust')
        for bad in ['123', 'abcdefghijkl', '1234567890123']:
            self.submit('500', utr=bad)
        self.assertEqual(Payment.objects.count(), 0)
        self.submit('500')
        self.submit('300')                                   # same UTR again
        self.assertEqual(Payment.objects.count(), 1)
        self.submit('2000', utr='111111111111')              # more than payable
        self.assertEqual(Payment.objects.count(), 1)

    def test_partial_upi_then_card_respects_pending(self):
        self.login('cust')
        self.submit('600')
        self.post('portal_booking_pay', self.b.pk, amount='500', method='Card')   # only Rs 400 payable now
        self.assertEqual(Payment.objects.count(), 1)
        self.post('portal_booking_pay', self.b.pk, amount='400', method='Card')
        self.assertEqual(Payment.objects.count(), 2)

    def test_staff_confirm_makes_it_paid_and_records_who(self):
        self.login('cust')
        self.submit('1000')
        p = Payment.objects.get()
        self.login('desk')
        self.post('batch_verify', p.batch.pk, action='confirm')
        p.refresh_from_db()
        self.assertEqual(p.status, 'Confirmed')
        self.assertEqual(p.verified_by.username, 'desk')
        self.assertIsNotNone(p.verified_at)
        self.assertEqual(self.b.payment_status, 'Paid')
        self.post('batch_verify', p.batch.pk, action='reject')    # already processed: no change
        p.refresh_from_db()
        self.assertEqual(p.status, 'Confirmed')

    def test_reject_frees_the_amount_and_utr_can_be_resubmitted(self):
        self.login('cust')
        self.submit('1000')
        p = Payment.objects.get()
        self.login('desk')
        self.post('batch_verify', p.batch.pk, action='reject')
        self.assertEqual(self.b.paid_total, 0)
        self.assertEqual(self.b.payable, Decimal('1000'))
        self.login('cust')
        self.submit('1000')                                   # same UTR allowed again after rejection
        self.assertEqual(Payment.objects.filter(status='Pending').count(), 1)

    def test_confirm_blocked_if_it_would_overpay(self):
        self.login('cust')
        self.submit('800', utr='222222222222')
        p = Payment.objects.get()
        self.login('desk')
        self.post('booking_add_payment', self.b.pk, amount='200', method='Cash', paid_on=date.today())
        Payment.objects.filter(pk=p.pk).update(amount=Decimal('900'))     # simulate edited / stale amount
        self.post('batch_verify', p.batch.pk, action='confirm')
        p.refresh_from_db()
        self.assertEqual(p.status, 'Pending')

    def test_who_may_verify(self):
        self.login('cust')
        self.submit('1000')
        p = Payment.objects.get()
        for who in ('cust', 'mech'):
            self.login(who)
            self.client.post(reverse('batch_verify', args=[p.batch.pk]), {'action': 'confirm'})
            p.refresh_from_db()
            self.assertEqual(p.status, 'Pending', who)

    def test_dashboard_and_pages_show_pending(self):
        self.login('cust')
        self.submit('1000')
        self.login('desk')
        self.assertContains(self.get('dashboard'), self.UTR)
        self.assertContains(self.get('booking_detail', self.b.pk), 'Confirm received')
        self.assertContains(self.get('payment_list'), 'Pending')
        self.login('cust')
        self.assertContains(self.get('portal_payments'), self.UTR)

    def test_cannot_pay_someone_elses_booking(self):
        self.login('cust')
        self.assertEqual(self.get('portal_pay_checkout', self.ob.pk).status_code, 404)
        self.assertEqual(self.post('portal_pay_upi', self.ob.pk, amount='1', utr=self.UTR).status_code, 404)

    def test_revenue_only_counts_confirmed(self):
        from django.db.models import Sum
        self.login('cust')
        self.submit('1000')
        self.login('boss')
        self.assertEqual(self.cust.total_spent, 0)
        r = self.get('dashboard')
        self.assertEqual(r.context['revenue_total'], 0)
        self.assertEqual(r.context['outstanding'], 1000)       # still owed until confirmed


class AccountTests(Base):
    def test_every_role_has_an_account_page(self):
        for who in ('boss', 'desk', 'mech', 'cust'):
            self.login(who)
            r = self.get('account')
            self.assertEqual(r.status_code, 200, who)
            self.assertContains(r, 'Change password')
        self.client.logout()
        self.assertEqual(self.get('account').status_code, 302)

    def test_customer_edits_details_and_phone_must_stay_unique(self):
        self.login('cust')
        self.post('account', action='details', name='A Sharma Jr', phone='9876543210', email='a@x.com',
                  city='Patiala', address='Model Town')
        self.cust.refresh_from_db()
        self.assertEqual((self.cust.name, self.cust.city), ('A Sharma Jr', 'Patiala'))
        self.assertEqual(User.objects.get(username='cust').first_name, 'A')
        self.post('account', action='details', name='A', phone=self.other.phone, email='', city='X', address='')
        self.cust.refresh_from_db()
        self.assertEqual(self.cust.phone, '9876543210')

    def test_mechanic_can_edit_phone_but_not_speciality(self):
        self.login('mech')
        r = self.get('account')
        self.assertNotContains(r, 'name="specialization"')
        self.post('account', action='details', name='M One', phone='9111111111', specialization='1')
        self.mech.refresh_from_db()
        self.assertEqual(self.mech.phone, '9111111111')
        self.assertIsNone(self.mech.specialization)

    def test_staff_and_admin_edit_name_and_email(self):
        for who in ('desk', 'boss'):
            self.login(who)
            self.post('account', action='details', first_name='Pat', last_name='Lee', email='pat@x.com')
            u = User.objects.get(username=who)
            self.assertEqual((u.first_name, u.email), ('Pat', 'pat@x.com'))

    def test_change_password_keeps_you_logged_in(self):
        self.login('cust')
        r = self.post('account', action='password', old_password='x', new_password1='Br4ndN3w!pass',
                      new_password2='Br4ndN3w!pass')
        self.assertContains(r, 'Password changed')
        self.assertEqual(self.get('portal_home').status_code, 200)           # still logged in
        self.client.logout()
        self.assertTrue(self.client.login(username='cust', password='Br4ndN3w!pass'))
        self.client.logout()
        self.assertFalse(self.client.login(username='cust', password='x'))

    def test_wrong_old_password_or_weak_new_password_rejected(self):
        self.login('cust')
        self.post('account', action='password', old_password='nope', new_password1='Br4ndN3w!pass',
                  new_password2='Br4ndN3w!pass')
        self.post('account', action='password', old_password='x', new_password1='123', new_password2='123')
        self.post('account', action='password', old_password='x', new_password1='Br4ndN3w!pass',
                  new_password2='Different!pass1')
        self.client.logout()
        self.assertTrue(self.client.login(username='cust', password='x'))     # unchanged


class PayTogetherTests(Base):
    """One UPI payment (one UTR) that settles several invoices."""
    UTR = '555555555555'

    def setUp(self):
        super().setUp()
        BookingService.objects.create(booking=self.b, service=self.svc, price=1000)       # invoice 1: Rs 1000
        svc2 = Service.objects.create(category=self.svc.category, name='Wash', price=500, duration_minutes=30)
        self.b2 = Booking.objects.create(car=self.car, mechanic=self.mech, booking_date=date.today())
        BookingService.objects.create(booking=self.b2, service=svc2, price=500)           # invoice 2: Rs 500
        self.login('cust')

    def multi_url(self, *ids):
        return reverse('portal_pay_multi') + '?' + '&'.join(f'b={i}' for i in ids)

    def submit(self, ids=None, total='1500', utr=None):
        ids = ids or [self.b.pk, self.b2.pk]
        return self.client.post(reverse('portal_pay_multi_submit'),
                                {'b': ids, 'total': total, 'utr': utr or self.UTR}, follow=True)

    def test_payments_page_offers_selection_with_total(self):
        r = self.get('portal_payments')
        self.assertContains(r, 'name="b"')
        self.assertContains(r, 'Pay selected together')
        self.assertEqual(r.context['owing_total'], Decimal('1500'))

    def test_combined_checkout_shows_sum_qr_and_link(self):
        r = self.client.get(self.multi_url(self.b.pk, self.b2.pk))
        self.assertContains(r, 'am=1500.00')
        self.assertContains(r, '<svg')
        self.assertContains(r, f'#{self.b.pk}')
        self.assertContains(r, f'#{self.b2.pk}')
        self.assertEqual(r.context['total'], Decimal('1500'))

    def test_one_utr_creates_one_batch_with_an_allocation_per_invoice(self):
        self.submit()
        batch = PaymentBatch.objects.get()
        self.assertEqual((batch.customer, batch.reference, batch.total_amount, batch.status),
                         (self.cust, self.UTR, Decimal('1500'), 'Pending'))
        rows = {p.booking_id: p for p in batch.payments.all()}
        self.assertEqual(rows[self.b.pk].amount, Decimal('1000'))
        self.assertEqual(rows[self.b2.pk].amount, Decimal('500'))
        self.assertTrue(all(p.status == 'Pending' and p.method == 'UPI' for p in rows.values()))
        for bk in (self.b, self.b2):
            self.assertEqual((bk.paid_total, bk.payment_status, bk.payable), (0, 'Verifying', 0))

    def test_staff_confirm_settles_every_invoice_at_once(self):
        self.submit()
        batch = PaymentBatch.objects.get()
        self.login('desk')
        self.assertContains(self.get('dashboard'), '2 invoices')
        self.post('batch_verify', batch.pk, action='confirm')
        batch.refresh_from_db()
        self.assertEqual((batch.status, batch.verified_by.username), ('Confirmed', 'desk'))
        self.assertEqual(Payment.objects.filter(status='Confirmed').count(), 2)
        self.assertEqual((self.b.payment_status, self.b2.payment_status), ('Paid', 'Paid'))

    def test_reject_frees_both_invoices_and_utr_can_be_resubmitted(self):
        self.submit()
        self.login('desk')
        self.post('batch_verify', PaymentBatch.objects.get().pk, action='reject')
        self.assertEqual(Payment.objects.filter(status='Rejected').count(), 2)
        self.assertEqual((self.b.payable, self.b2.payable), (Decimal('1000'), Decimal('500')))
        self.login('cust')
        self.submit()                                                      # same UTR again is fine after rejection
        self.assertEqual(PaymentBatch.objects.filter(status='Pending').count(), 1)

    def test_confirm_is_all_or_nothing(self):
        self.submit()
        self.login('desk')
        # a Rs 100 cash payment was recorded on invoice 2 after the customer submitted the UPI payment
        Payment.objects.create(booking=self.b2, amount=Decimal('100'), method='Cash')
        self.post('batch_verify', PaymentBatch.objects.get().pk, action='confirm')       # would overpay invoice 2
        self.assertEqual(PaymentBatch.objects.get().status, 'Pending')
        self.assertEqual(Payment.objects.filter(status='Confirmed').count(), 1)           # only the Cash one

    def test_total_is_recomputed_on_the_server(self):
        self.submit(total='1')                                             # tampered / stale total
        self.assertEqual(PaymentBatch.objects.count(), 0)

    def test_utr_rules_apply(self):
        for bad in ('123', 'abcdefghijkl'):
            self.submit(utr=bad)
        self.assertEqual(PaymentBatch.objects.count(), 0)
        self.submit()
        self.submit(ids=[self.b.pk], total='1000', utr=self.UTR)           # same UTR on something else
        self.assertEqual(PaymentBatch.objects.count(), 1)

    def test_other_customers_and_cancelled_invoices_are_ignored(self):
        BookingService.objects.create(booking=self.ob, service=self.svc, price=900)
        self.submit(ids=[self.b.pk, self.b2.pk, self.ob.pk])
        batch = PaymentBatch.objects.get()
        self.assertEqual(batch.payments.count(), 2)                         # the other customer's invoice is skipped
        self.assertFalse(Payment.objects.filter(booking=self.ob).exists())
        # only someone else's invoice selected: nothing is created
        self.login('cust2')
        self.client.post(reverse('portal_pay_multi_submit'), {'b': [self.b.pk], 'total': '1000', 'utr': '666666666666'})
        self.assertEqual(PaymentBatch.objects.filter(reference='666666666666').count(), 0)

    def test_cancelled_invoice_cannot_be_included(self):
        Booking.objects.filter(pk=self.b2.pk).update(status='Cancelled')
        self.submit(ids=[self.b.pk, self.b2.pk], total='1000')
        batch = PaymentBatch.objects.get()
        self.assertEqual([p.booking_id for p in batch.payments.all()], [self.b.pk])

    def test_one_selected_invoice_goes_to_normal_checkout(self):
        r = self.client.get(self.multi_url(self.b.pk))
        self.assertRedirects(r, reverse('portal_pay_checkout', args=[self.b.pk]), fetch_redirect_response=False)
        r = self.client.get(reverse('portal_pay_multi'))                    # nothing selected
        self.assertRedirects(r, reverse('portal_payments'), fetch_redirect_response=False)

    def test_history_and_staff_booking_page_show_the_combined_payment(self):
        self.submit()
        self.assertContains(self.get('portal_payments'), self.UTR)
        self.login('desk')
        r = self.get('booking_detail', self.b.pk)
        self.assertContains(r, 'covering 2 invoices')
        self.assertContains(r, 'Confirm received')

    def test_only_customers_can_use_pay_together(self):
        self.login('mech')
        self.assertEqual(self.client.get(self.multi_url(self.b.pk, self.b2.pk)).status_code, 302)
        self.login('desk')
        self.assertEqual(self.client.get(self.multi_url(self.b.pk, self.b2.pk)).status_code, 302)
