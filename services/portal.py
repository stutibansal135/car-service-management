"""Customer portal, mechanic portal and public pages."""
import secrets
from decimal import Decimal
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import auth, messages
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import forms, upi
from .access import CUSTOMER, HOME, MECHANIC, STAFF, role_required, user_role

ALL_ROLES = ('admin', 'staff', 'mechanic', 'customer')
from .models import (Booking, BookingService, Car, Customer, Feedback, Payment, PaymentBatch, Profile,
                     Service, ServiceCategory)
from .views import (CreateBase, ListBase, UpdateBase, _errors, add_part_to_booking, apply_status)


# =========================================================== public / auth
def after_login(request):
    """Send each role to its own home page."""
    role = user_role(request.user)
    if role is None:
        if request.user.is_authenticated:
            auth.logout(request)
            messages.error(request, "This account isn't active. Please ask the workshop admin.")
        return redirect('home')
    return redirect(HOME[role])


def signup(request):
    if request.user.is_authenticated:
        return redirect('after_login')
    form = forms.SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            user = auth.get_user_model().objects.create_user(
                d['username'], d['email'], d['password'], first_name=d['name'].split()[0])
            cust = Customer.objects.create(name=d['name'], phone=d['phone'], email=d['email'])
            Profile.objects.create(user=user, role='customer', customer=cust)
        auth.login(request, user)
        messages.success(request, "Welcome! Add your car to get started.")
        return redirect('portal_home')
    return render(request, 'services/signup.html', {'form': form})


def about(request):
    return render(request, 'services/about.html')


def track(request):
    reg = request.GET.get('reg', '').upper().replace(' ', '').replace('-', '')
    jobs = None
    if reg:
        jobs = (Booking.objects.filter(car__registration_number=reg).select_related('car')
                .prefetch_related('service_items__service').order_by('-booking_date')[:3])
    return render(request, 'services/track.html', {'reg': reg, 'jobs': jobs})


# ================================================================ invoices
def _invoice_ctx(b, back_url):
    return {'b': b, 'service_items': b.service_items.select_related('service'),
            'part_items': b.part_items.select_related('part'),
            'payments': b.payments.filter(status=Payment.CONFIRMED),
            'services_total': b.services_total, 'parts_total': b.parts_total, 'total': b.total,
            'paid': b.paid_total, 'balance': b.balance, 'back_url': back_url}


@role_required(*STAFF)
def invoice(request, pk):
    b = get_object_or_404(Booking.objects.select_related('car', 'car__customer', 'mechanic'), pk=pk)
    return render(request, 'services/invoice.html', _invoice_ctx(b, reverse('booking_detail', args=[pk])))


# ========================================================= customer portal
def _customer(request):
    return request.user.profile.customer


def _own_booking(request, pk):
    return get_object_or_404(Booking.objects.select_related('car', 'car__customer', 'mechanic'),
                             pk=pk, car__customer=_customer(request))


@role_required(*CUSTOMER)
def portal_home(request):
    c = _customer(request)
    mine = Booking.objects.filter(car__customer=c)
    active = mine.filter(status__in=[Booking.PENDING, Booking.IN_PROGRESS]) \
        .select_related('car', 'mechanic').order_by('booking_date')
    unpaid = [b for b in mine.exclude(status=Booking.CANCELLED).select_related('car') if b.balance > 0]
    return render(request, 'portal/home.html', {
        'c': c, 'n_cars': c.cars.count(), 'active': active, 'unpaid': unpaid,
        'dues': sum((b.balance for b in unpaid), Decimal('0')),
        'recent': mine.filter(status=Booking.COMPLETED).select_related('car')[:5],
        'visits': mine.filter(status=Booking.COMPLETED).count(),
    })


class PortalCarList(ListBase):
    roles = CUSTOMER
    model = Car
    title, prefix = 'My cars', 'portal_car'
    can_delete = False
    search_fields = ['registration_number', 'brand', 'model']
    columns = [('Reg. no.', 'registration_number'), ('Car', 'full_name'), ('Fuel', 'fuel_type'), ('Colour', 'color')]

    def get_queryset(self):
        return super().get_queryset().filter(customer=_customer(self.request))


class PortalCarCreate(CreateBase):
    roles = CUSTOMER
    model, form_class, title = Car, forms.PortalCarForm, 'Add a car'
    list_url = 'portal_cars'

    def form_valid(self, form):
        form.instance.customer = _customer(self.request)
        return super().form_valid(form)


class PortalCarUpdate(UpdateBase):
    roles = CUSTOMER
    model, form_class, title = Car, forms.PortalCarForm, 'Edit car'
    list_url = 'portal_cars'

    def get_queryset(self):
        return Car.objects.filter(customer=_customer(self.request))


class PortalBookingList(ListBase):
    roles = CUSTOMER
    model = Booking
    title, prefix, has_detail = 'My bookings', 'portal_booking', True
    can_add = can_edit = can_delete = False
    search_fields = ['car__registration_number', 'car__brand', 'car__model']
    columns = [('#', 'id'), ('Date', 'booking_date'), ('Car', 'car.registration_number'),
               ('Services', 'service_summary'), ('Status', 'status'), ('Total', 'total'), ('Payment', 'payment_status')]
    filter_param, filter_label = 'status', 'Status'

    def get_filter_choices(self):
        return Booking.STATUS_CHOICES

    def get_queryset(self):
        return (super().get_queryset().filter(car__customer=_customer(self.request))
                .select_related('car').prefetch_related('service_items__service'))


@role_required(*CUSTOMER)
def portal_book_new(request):
    cust = _customer(request)
    if not cust.cars.exists():
        messages.error(request, "Add your car first, then you can book a service.")
        return redirect('portal_car_add')
    form = forms.BookServiceForm(request.POST or None, customer=cust,
                                 initial={'car': request.GET.get('car'),
                                          'booking_date': timezone.localdate()})
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        with transaction.atomic():
            b = Booking.objects.create(car=d['car'], booking_date=d['booking_date'], notes=d['notes'])
            for s in d['services']:
                BookingService.objects.create(booking=b, service=s, price=s.price)
        messages.success(request, "Booking requested! We'll assign a mechanic shortly.")
        return redirect('portal_booking_detail', pk=b.pk)
    groups = [(c, [s for s in c.services.all() if s.is_active])
              for c in ServiceCategory.objects.prefetch_related('services').order_by('name')]
    return render(request, 'portal/book.html', {
        'form': form, 'groups': [g for g in groups if g[1]],
        'selected': request.POST.getlist('services') if request.method == 'POST' else []})


@role_required(*CUSTOMER)
def portal_booking_detail(request, pk):
    b = _own_booking(request, pk)
    ctx = _invoice_ctx(b, reverse('portal_bookings'))
    ctx.update(all_payments=b.payments.all(), pending=b.pending_total, payable=b.payable,
               feedback_form=forms.FeedbackForm(), can_cancel=b.status == Booking.PENDING,
               can_pay=b.status != Booking.CANCELLED and b.payable > 0)
    return render(request, 'portal/booking_detail.html', ctx)


@role_required(*CUSTOMER)
def portal_invoice(request, pk):
    b = _own_booking(request, pk)
    return render(request, 'services/invoice.html', _invoice_ctx(b, reverse('portal_booking_detail', args=[pk])))


@role_required(*CUSTOMER)
@require_POST
def portal_booking_cancel(request, pk):
    b = _own_booking(request, pk)
    if b.status != Booking.PENDING:
        messages.error(request, "Work has already started on this booking, so it can't be cancelled online. "
                                "Please call the workshop.")
    else:
        apply_status(request, b, Booking.CANCELLED)
    return redirect('portal_booking_detail', pk=pk)


@role_required(*CUSTOMER)
@require_POST
def portal_booking_pay(request, pk):
    """DEMO card / net-banking checkout: confirmed instantly, no real money. (UPI has its own real flow.)"""
    b = _own_booking(request, pk)
    if b.status == Booking.CANCELLED or b.total == 0:
        messages.error(request, "There is nothing to pay on this booking.")
    elif b.payable <= 0:
        messages.error(request, "Nothing left to pay on this booking.")
    else:
        form = forms.DemoPayForm(request.POST, booking=b)
        if form.is_valid():
            Payment.objects.create(booking=b, amount=form.cleaned_data['amount'],
                                   method=form.cleaned_data['method'], paid_on=timezone.localdate(),
                                   status=Payment.CONFIRMED,
                                   reference='DEMO' + ''.join(secrets.choice('0123456789') for _ in range(10)))
            messages.success(request, "Payment successful (demo checkout - no real money moved).")
        else:
            messages.error(request, _errors(form))
    return redirect('portal_booking_detail', pk=pk)


# ---------------------------------------------------------- customer payments + UPI
@role_required(*CUSTOMER)
def portal_payments(request):
    c = _customer(request)
    bookings = list(Booking.objects.filter(car__customer=c).exclude(status=Booking.CANCELLED)
                    .select_related('car'))
    owing = [b for b in bookings if b.payable > 0]
    payments = (Payment.objects.filter(booking__car__customer=c)
                .select_related('booking', 'booking__car').order_by('-paid_on', '-id'))
    return render(request, 'portal/payments.html', {
        'owing': owing, 'owing_total': sum((b.payable for b in owing), Decimal('0')),
        'due': sum((b.balance for b in bookings if b.balance > 0), Decimal('0')),
        'paid': sum((p.amount for p in payments if p.status == Payment.CONFIRMED), Decimal('0')),
        'pending': sum((p.amount for p in payments if p.status == Payment.PENDING), Decimal('0')),
        'payments': payments[:100],
    })


@role_required(*CUSTOMER)
def portal_pay_checkout(request, pk):
    """UPI checkout: pick the amount, scan the QR / open a UPI app, then submit the transaction ID."""
    b = _own_booking(request, pk)
    if b.status == Booking.CANCELLED or b.payable <= 0:
        messages.error(request, "Nothing left to pay on this booking.")
        return redirect('portal_booking_detail', pk=pk)
    try:
        amount = Decimal(request.GET.get('amount', b.payable)).quantize(Decimal('0.01'))
    except Exception:
        amount = b.payable
    if amount <= 0 or amount > b.payable:
        amount = b.payable
    uri = upi.upi_uri(settings.UPI_ID, settings.UPI_PAYEE_NAME, amount, f"CSM Booking {b.pk}")
    return render(request, 'portal/checkout.html', {
        'b': b, 'amount': amount, 'upi_id': settings.UPI_ID, 'payee': settings.UPI_PAYEE_NAME,
        'upi_uri': uri, 'qr': upi.qr_svg(uri), 'form': forms.UpiSubmitForm(initial={'amount': amount}),
        'demo_form': forms.DemoPayForm(booking=b), 'total': b.total, 'paid': b.paid_total,
        'pending': b.pending_total, 'payable': b.payable})


def _create_upi_batch(customer, allocations, utr):
    """allocations = [(booking, amount), ...] -> one PaymentBatch (one UTR) + one Pending Payment per booking."""
    today = timezone.localdate()
    with transaction.atomic():
        batch = PaymentBatch.objects.create(customer=customer, reference=utr, created_on=today,
                                            total_amount=sum((amt for _, amt in allocations), Decimal('0')))
        for b, amt in allocations:
            Payment.objects.create(booking=b, amount=amt, method='UPI', reference=utr, paid_on=today,
                                   status=Payment.PENDING, batch=batch)
    return batch


SUBMITTED_MSG = ("Thanks! We've received your transaction ID. The workshop will confirm your payment "
                 "as soon as it shows in our bank account.")
DUPLICATE_MSG = "This transaction ID has already been submitted."


@role_required(*CUSTOMER)
@require_POST
def portal_pay_upi(request, pk):
    """Customer paid ONE invoice by UPI and reports the transaction ID."""
    b = _own_booking(request, pk)
    if b.status == Booking.CANCELLED or b.payable <= 0:
        messages.error(request, "Nothing left to pay on this booking.")
        return redirect('portal_booking_detail', pk=pk)
    form = forms.UpiSubmitForm(request.POST, booking=b)
    if form.is_valid():
        try:
            _create_upi_batch(_customer(request), [(b, form.cleaned_data['amount'])], form.cleaned_data['utr'])
        except IntegrityError:
            messages.error(request, DUPLICATE_MSG)
        else:
            messages.success(request, SUBMITTED_MSG)
            return redirect('portal_payments')
    else:
        messages.error(request, _errors(form))
    return redirect(f"{reverse('portal_pay_checkout', args=[pk])}?amount={request.POST.get('amount', '')}")


# ---- pay several invoices together with ONE UPI payment
def _pay_selection(request, ids):
    """The customer's own, still-payable bookings among the selected ids."""
    wanted = [int(i) for i in ids[:30] if str(i).isdigit()]
    bs = (Booking.objects.filter(pk__in=wanted, car__customer=_customer(request))
          .exclude(status=Booking.CANCELLED).select_related('car').order_by('booking_date', 'id'))
    return [b for b in bs if b.payable > 0]


@role_required(*CUSTOMER)
def portal_pay_multi(request):
    bs = _pay_selection(request, request.GET.getlist('b'))
    if not bs:
        messages.error(request, "Select at least one invoice that still has an amount to pay.")
        return redirect('portal_payments')
    if len(bs) == 1:                                   # one invoice: use the normal checkout (allows part payment)
        return redirect('portal_pay_checkout', pk=bs[0].pk)
    total = sum((b.payable for b in bs), Decimal('0'))
    note = ("CSM bookings " + ",".join(str(b.pk) for b in bs)) if len(bs) <= 4 else f"CSM {len(bs)} bookings"
    uri = upi.upi_uri(settings.UPI_ID, settings.UPI_PAYEE_NAME, total, note)
    return render(request, 'portal/checkout_multi.html', {
        'items': [(b, b.payable) for b in bs], 'total': total, 'upi_id': settings.UPI_ID,
        'payee': settings.UPI_PAYEE_NAME, 'upi_uri': uri, 'qr': upi.qr_svg(uri), 'note': note,
        'form': forms.UtrForm()})


@role_required(*CUSTOMER)
@require_POST
def portal_pay_multi_submit(request):
    ids = request.POST.getlist('b')
    bs = _pay_selection(request, ids)
    back = reverse('portal_pay_multi') + '?' + urlencode([('b', i) for i in ids])
    if not bs:
        messages.error(request, "Nothing left to pay on those invoices.")
        return redirect('portal_payments')
    allocations = [(b, b.payable) for b in bs]              # amounts are always recomputed on the server
    total = sum((amt for _, amt in allocations), Decimal('0'))
    try:
        sent = Decimal(request.POST.get('total', ''))
    except Exception:
        sent = None
    form = forms.UtrForm(request.POST)
    if sent != total:
        messages.error(request, "The amounts have changed since you opened this page. Please check and try again.")
    elif not form.is_valid():
        messages.error(request, _errors(form))
    else:
        try:
            _create_upi_batch(_customer(request), allocations, form.cleaned_data['utr'])
        except IntegrityError:
            messages.error(request, DUPLICATE_MSG)
        else:
            messages.success(request, SUBMITTED_MSG)
            return redirect('portal_payments')
    return redirect(back)


@role_required(*CUSTOMER)
@require_POST
def portal_booking_feedback(request, pk):
    b = _own_booking(request, pk)
    form = forms.FeedbackForm(request.POST)
    if b.status != Booking.COMPLETED:
        messages.error(request, "You can rate a job once it is completed.")
    elif form.is_valid():
        Feedback.objects.update_or_create(booking=b, defaults=form.cleaned_data)
        messages.success(request, "Thanks for your feedback!")
    else:
        messages.error(request, _errors(form))
    return redirect('portal_booking_detail', pk=pk)


# ============================================================ My account (all roles)
def _details_form(request, data=None):
    role, user = user_role(request.user), request.user
    if role == 'customer':
        return forms.CustomerForm(data, instance=user.profile.customer)
    if role == 'mechanic':
        return forms.MechanicSelfForm(data, instance=user.profile.mechanic)
    return forms.UserDetailsForm(data, instance=user)


@role_required(*ALL_ROLES)
def account(request):
    user, role = request.user, user_role(request.user)
    details, pw = _details_form(request), forms.PasswordForm(user)
    if request.method == 'POST':
        if request.POST.get('action') == 'password':
            pw = forms.PasswordForm(user, request.POST)
            if pw.is_valid():
                pw.save()
                auth.update_session_auth_hash(request, pw.user)        # stay logged in
                messages.success(request, "Password changed.")
                return redirect('account')
        else:
            details = _details_form(request, request.POST)
            if details.is_valid():
                obj = details.save()
                if role in ('customer', 'mechanic'):                    # keep the login's name in step
                    user.first_name = obj.name.split()[0]
                    if role == 'customer':
                        user.email = obj.email
                    user.save(update_fields=['first_name', 'email'])
                messages.success(request, "Your details were saved.")
                return redirect('account')
    profile = getattr(user, 'profile', None)
    ctx = {'details': details, 'pw': pw, 'u': user,
           'customer': profile.customer if role == 'customer' else None,
           'mechanic': profile.mechanic if role == 'mechanic' else None}
    if ctx['customer']:
        ctx['n_cars'] = ctx['customer'].cars.count()
    return render(request, 'portal/account.html', ctx)


# ========================================================= mechanic portal
def _mechanic(request):
    return request.user.profile.mechanic


def _own_job(request, pk):
    return get_object_or_404(Booking.objects.select_related('car', 'car__customer'),
                             pk=pk, mechanic=_mechanic(request))


@role_required(*MECHANIC)
def mech_home(request):
    m = _mechanic(request)
    mine = Booking.objects.filter(mechanic=m)
    today = timezone.localdate()
    open_jobs = mine.filter(status__in=[Booking.PENDING, Booking.IN_PROGRESS])
    ratings = Feedback.objects.filter(booking__mechanic=m)
    return render(request, 'portal/mech_home.html', {
        'm': m,
        'open_count': open_jobs.count(),
        'today_count': open_jobs.filter(booking_date=today).count(),
        'done_month': mine.filter(status=Booking.COMPLETED, booking_date__gte=today.replace(day=1)).count(),
        'done_total': mine.filter(status=Booking.COMPLETED).count(),
        'avg_rating': ratings.aggregate(a=Avg('rating'))['a'],
        'rating_count': ratings.count(),
        'upcoming': open_jobs.select_related('car').prefetch_related('service_items__service').order_by('booking_date')[:8],
        'feedback': ratings.select_related('booking__car').order_by('-booking__booking_date')[:4],
    })


class MechJobList(ListBase):
    roles = MECHANIC
    model = Booking
    title, prefix, has_detail = 'My jobs', 'mech_job', True
    can_add = can_edit = can_delete = False
    search_fields = ['car__registration_number', 'car__brand', 'car__model']
    columns = [('#', 'id'), ('Date', 'booking_date'), ('Car', 'car.registration_number'),
               ('Services', 'service_summary'), ('Status', 'status')]
    filter_param, filter_label = 'status', 'Status'

    def get_filter_choices(self):
        return Booking.STATUS_CHOICES

    def get_queryset(self):
        return (super().get_queryset().filter(mechanic=_mechanic(self.request))
                .select_related('car').prefetch_related('service_items__service'))


@role_required(*MECHANIC)
def mech_job_detail(request, pk):
    b = _own_job(request, pk)
    next_status = {Booking.PENDING: Booking.IN_PROGRESS, Booking.IN_PROGRESS: Booking.COMPLETED}.get(b.status)
    return render(request, 'portal/mech_job.html', {
        'b': b, 'service_items': b.service_items.select_related('service'),
        'part_items': b.part_items.select_related('part'),
        'part_form': forms.AddPartForm(booking=b, show_price=False), 'note_form': forms.MechanicNoteForm(),
        'next_status': next_status})


@role_required(*MECHANIC)
@require_POST
def mech_job_status(request, pk):
    b = _own_job(request, pk)
    new = request.POST.get('status')
    if new in (Booking.IN_PROGRESS, Booking.COMPLETED):     # mechanics can't cancel jobs
        apply_status(request, b, new)
    else:
        messages.error(request, "Mechanics can start or complete jobs only.")
    return redirect('mech_job_detail', pk=pk)


@role_required(*MECHANIC)
@require_POST
def mech_job_add_part(request, pk):
    add_part_to_booking(request, _own_job(request, pk), request.POST, show_price=False)
    return redirect('mech_job_detail', pk=pk)


@role_required(*MECHANIC)
@require_POST
def mech_job_note(request, pk):
    b = _own_job(request, pk)
    form = forms.MechanicNoteForm(request.POST)
    if not b.can_edit_items:
        messages.error(request, "This job is closed.")
    elif form.is_valid():
        line = f"[{timezone.localdate():%d %b}] {form.cleaned_data['note']}"
        b.notes = (b.notes + "\n" + line).strip()
        b.save(update_fields=['notes'])
        messages.success(request, "Note added.")
    else:
        messages.error(request, _errors(form))
    return redirect('mech_job_detail', pk=pk)
