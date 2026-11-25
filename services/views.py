from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.messages.views import SuccessMessageMixin
from django.db import connection, transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.db.models.deletion import ProtectedError
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from . import forms
from .access import ADMIN, STAFF, RoleMixin, role_required, user_role
from .models import (Booking, BookingPart, BookingService, Car, Customer, Feedback, Mechanic,
                     Part, Payment, PaymentBatch, Service, ServiceCategory, Supplier)
from .reports import REPORTS


# ---------------------------------------------------------------- public home
def home(request):
    categories = ServiceCategory.objects.prefetch_related('services').order_by('name')
    return render(request, 'services/home.html', {
        'categories': [(c, [s for s in c.services.all() if s.is_active]) for c in categories],
        'stats': {'cars': Car.objects.count(), 'bookings': Booking.objects.filter(status='Completed').count(),
                  'mechanics': Mechanic.objects.filter(is_active=True).count()},
    })


# ------------------------------------------------------------------ dashboard
@role_required(*STAFF)
def dashboard(request):
    today = timezone_today()
    month_start = today.replace(day=1)
    pay = Payment.objects.filter(status=Payment.CONFIRMED)      # only verified money counts as revenue
    with connection.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(balance_due),0) FROM vw_booking_balance "
                    "WHERE status <> 'Cancelled' AND balance_due > 0")
        outstanding = cur.fetchone()[0]

    # last 6 months of revenue (zero-filled)
    first = (month_start - timedelta(days=150)).replace(day=1)
    raw = {r['m']: r['t'] for r in pay.filter(paid_on__gte=first).annotate(m=TruncMonth('paid_on'))
           .values('m').annotate(t=Sum('amount'))}
    months, cur_m = [], month_start
    for _ in range(6):
        months.append(cur_m)
        cur_m = (cur_m - timedelta(days=1)).replace(day=1)
    months.reverse()
    monthly = [(m, raw.get(m, Decimal('0'))) for m in months]

    statuses = {r['status']: r['n'] for r in Booking.objects.values('status').annotate(n=Count('id'))}
    status_rows = [(s, statuses.get(s, 0)) for s, _ in Booking.STATUS_CHOICES]

    ctx = {
        'customers': Customer.objects.count(),
        'cars': Car.objects.count(),
        'bookings': Booking.objects.count(),
        'revenue_total': pay.aggregate(t=Sum('amount'))['t'] or 0,
        'revenue_month': pay.filter(paid_on__gte=month_start).aggregate(t=Sum('amount'))['t'] or 0,
        'outstanding': outstanding,
        'open_jobs': Booking.objects.filter(status__in=[Booking.PENDING, Booking.IN_PROGRESS]).count(),
        'avg_rating': Feedback.objects.aggregate(a=Avg('rating'))['a'],
        'monthly': monthly,
        'monthly_max': max([t for _, t in monthly] + [Decimal('1')]),
        'status_rows': status_rows,
        'status_total': sum(statuses.values()) or 1,
        'top_services': BookingService.objects.filter(booking__status=Booking.COMPLETED)
            .values('service__name').annotate(n=Count('id'), rev=Sum('price')).order_by('-n')[:6],
        'workload': Mechanic.objects.filter(is_active=True).annotate(
            jobs=Count('bookings', filter=Q(bookings__status__in=[Booking.PENDING, Booking.IN_PROGRESS])))
            .order_by('-jobs', 'name')[:6],
        'pending_batches': PaymentBatch.objects.filter(status='Pending').select_related('customer')
            .prefetch_related('payments').order_by('created_on', 'id')[:8],
        'pending_count': PaymentBatch.objects.filter(status='Pending').count(),
        'low_stock': Part.objects.filter(stock_qty__lte=F('reorder_level')).order_by('stock_qty')[:6],
        'low_stock_count': Part.objects.filter(stock_qty__lte=F('reorder_level')).count(),
        'upcoming': Booking.objects.filter(status__in=[Booking.PENDING, Booking.IN_PROGRESS])
            .select_related('car', 'car__customer', 'mechanic').order_by('booking_date')[:7],
    }
    return render(request, 'services/dashboard.html', ctx)


def timezone_today():
    return timezone.localdate()


# ------------------------------------------------------- generic list/CRUD views
class ListBase(RoleMixin, ListView):
    template_name = 'services/list.html'
    paginate_by = 15
    title = ''
    prefix = ''                 # url-name prefix: <prefix>_add / _edit / _delete / _detail
    columns = []                # [(header, 'dotted.path')]
    search_fields = []
    has_detail = False
    can_add = True
    can_edit = True
    can_delete = None            # None = only the admin role
    filter_param = None
    filter_label = ''

    def get_filter_choices(self):
        return []

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get('q', '').strip()
        if q:
            cond = Q()
            for f in self.search_fields:
                cond |= Q(**{f + '__icontains': q})
            if q.isdigit() and hasattr(self, 'id_search'):
                cond |= Q(pk=int(q))
            qs = qs.filter(cond)
        if self.filter_param and self.request.GET.get('f'):
            qs = qs.filter(**{self.filter_param: self.request.GET['f']})
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        params = self.request.GET.copy()
        params.pop('page', None)
        ctx.update(
            title=self.title, prefix=self.prefix, columns=self.columns, has_detail=self.has_detail,
            can_add=self.can_add, can_edit=self.can_edit,
            can_delete=(user_role(self.request.user) == 'admin') if self.can_delete is None else self.can_delete,
            q=self.request.GET.get('q', ''),
            filter_choices=self.get_filter_choices() if self.filter_param else None,
            filter_label=self.filter_label, f=self.request.GET.get('f', ''),
            querystring=params.urlencode(), count=ctx['paginator'].count,
        )
        return ctx


class FormMixin(RoleMixin, SuccessMessageMixin):
    template_name = 'services/form.html'
    title = ''
    prefix = ''
    list_url = None              # url name to return to; defaults to '<prefix>_list'

    def get_list_url(self):
        return reverse(self.list_url or self.prefix + '_list')

    def get_success_url(self):
        return self.get_list_url()

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx.update(title=self.title, cancel_url=self.get_list_url())
        return ctx


class CreateBase(FormMixin, CreateView):
    success_message = "Created successfully."


class UpdateBase(FormMixin, UpdateView):
    success_message = "Saved changes."


class DeleteBase(RoleMixin, DeleteView):
    roles = ADMIN
    template_name = 'services/confirm_delete.html'
    prefix = ''

    def get_success_url(self):
        return reverse(self.prefix + '_list')

    def delete_object(self, obj):
        obj.delete()

    def form_valid(self, form):
        obj = self.get_object()
        try:
            with transaction.atomic():
                self.delete_object(obj)
        except ProtectedError:
            messages.error(self.request, "Can't delete this record because other records depend on it "
                                         "(for example bookings or payments). Remove or reassign those first.")
        else:
            messages.success(self.request, "Deleted.")
        return redirect(self.get_success_url())


# ---- customers
class CustomerList(ListBase):
    model = Customer
    title, prefix, has_detail = 'Customers', 'customer', True
    search_fields = ['name', 'phone', 'email', 'city']
    columns = [('Name', 'name'), ('Phone', 'phone'), ('Email', 'email'), ('City', 'city'), ('Cars', 'car_count')]
    filter_param, filter_label = 'city', 'City'

    def get_queryset(self):
        return super().get_queryset().annotate(car_count=Count('cars')).order_by('name')

    def get_filter_choices(self):
        return [(c, c) for c in Customer.objects.order_by('city').values_list('city', flat=True).distinct()]


class CustomerCreate(CreateBase):
    model, form_class, title, prefix = Customer, forms.CustomerForm, 'Add customer', 'customer'


class CustomerUpdate(UpdateBase):
    model, form_class, title, prefix = Customer, forms.CustomerForm, 'Edit customer', 'customer'


class CustomerDelete(DeleteBase):
    model, prefix = Customer, 'customer'


@role_required(*STAFF)
def customer_detail(request, pk):
    c = get_object_or_404(Customer, pk=pk)
    return render(request, 'services/customer_detail.html', {
        'c': c,
        'cars': c.cars.annotate(n=Count('bookings')),
        'bookings': Booking.objects.filter(car__customer=c).select_related('car', 'mechanic')[:25],
    })


# ---- cars
class CarList(ListBase):
    model = Car
    title, prefix = 'Cars', 'car'
    search_fields = ['registration_number', 'brand', 'model', 'customer__name']
    columns = [('Reg. no.', 'registration_number'), ('Car', 'full_name'), ('Fuel', 'fuel_type'),
               ('Colour', 'color'), ('Owner', 'customer.name')]
    filter_param, filter_label = 'fuel_type', 'Fuel'

    def get_queryset(self):
        return super().get_queryset().select_related('customer')

    def get_filter_choices(self):
        return Car.FUEL_CHOICES


class CarCreate(CreateBase):
    model, form_class, title, prefix = Car, forms.CarForm, 'Add car', 'car'

    def get_initial(self):
        init = super().get_initial()
        if self.request.GET.get('customer'):
            init['customer'] = self.request.GET['customer']
        return init


class CarUpdate(UpdateBase):
    model, form_class, title, prefix = Car, forms.CarForm, 'Edit car', 'car'


class CarDelete(DeleteBase):
    model, prefix = Car, 'car'


# ---- services
class ServiceList(ListBase):
    roles = ADMIN
    model = Service
    title, prefix = 'Services', 'service'
    search_fields = ['name', 'description', 'category__name']
    columns = [('Service', 'name'), ('Category', 'category.name'), ('Price', 'price'),
               ('Duration (min)', 'duration_minutes'), ('Status', 'is_active')]
    filter_param, filter_label = 'category_id', 'Category'

    def get_queryset(self):
        return super().get_queryset().select_related('category')

    def get_filter_choices(self):
        return [(c.id, c.name) for c in ServiceCategory.objects.all()]


class ServiceCreate(CreateBase):
    roles = ADMIN
    model, form_class, title, prefix = Service, forms.ServiceForm, 'Add service', 'service'


class ServiceUpdate(UpdateBase):
    roles = ADMIN
    model, form_class, title, prefix = Service, forms.ServiceForm, 'Edit service', 'service'


class ServiceDelete(DeleteBase):
    model, prefix = Service, 'service'


# ---- mechanics
class MechanicList(ListBase):
    roles = ADMIN
    model = Mechanic
    title, prefix = 'Mechanics', 'mechanic'
    search_fields = ['name', 'phone', 'specialization__name']
    columns = [('Name', 'name'), ('Phone', 'phone'), ('Specialisation', 'specialization.name'),
               ('Hired on', 'hire_date'), ('Jobs done', 'done'), ('Status', 'is_active')]

    def get_queryset(self):
        return super().get_queryset().select_related('specialization').annotate(
            done=Count('bookings', filter=Q(bookings__status='Completed'))).order_by('name')


class MechanicCreate(CreateBase):
    roles = ADMIN
    model, form_class, title, prefix = Mechanic, forms.MechanicForm, 'Add mechanic', 'mechanic'


class MechanicUpdate(UpdateBase):
    roles = ADMIN
    model, form_class, title, prefix = Mechanic, forms.MechanicForm, 'Edit mechanic', 'mechanic'


class MechanicDelete(DeleteBase):
    model, prefix = Mechanic, 'mechanic'


# ---- suppliers
class SupplierList(ListBase):
    roles = ADMIN
    model = Supplier
    title, prefix = 'Suppliers', 'supplier'
    search_fields = ['name', 'city', 'phone']
    columns = [('Supplier', 'name'), ('City', 'city'), ('Phone', 'phone'), ('Email', 'email'),
               ('Parts supplied', 'n_parts')]

    def get_queryset(self):
        return super().get_queryset().annotate(n_parts=Count('parts')).order_by('name')


class SupplierCreate(CreateBase):
    roles = ADMIN
    model, form_class, title, prefix = Supplier, forms.SupplierForm, 'Add supplier', 'supplier'


class SupplierUpdate(UpdateBase):
    roles = ADMIN
    model, form_class, title, prefix = Supplier, forms.SupplierForm, 'Edit supplier', 'supplier'


class SupplierDelete(DeleteBase):
    model, prefix = Supplier, 'supplier'


# ---- parts (inventory)
class PartList(ListBase):
    roles = ADMIN
    model = Part
    title, prefix = 'Parts inventory', 'part'
    search_fields = ['name', 'sku', 'supplier__name']
    columns = [('SKU', 'sku'), ('Part', 'name'), ('Supplier', 'supplier.name'), ('Unit price', 'unit_price'),
               ('In stock', 'stock_qty'), ('Re-order at', 'reorder_level'), ('Status', 'stock_status')]
    filter_param, filter_label = 'supplier_id', 'Supplier'

    def get_queryset(self):
        qs = super().get_queryset().select_related('supplier')
        if self.request.GET.get('low'):
            qs = qs.filter(stock_qty__lte=F('reorder_level'))
        return qs

    def get_filter_choices(self):
        return [(s.id, s.name) for s in Supplier.objects.all()]


class PartCreate(CreateBase):
    roles = ADMIN
    model, form_class, title, prefix = Part, forms.PartForm, 'Add part', 'part'


class PartUpdate(UpdateBase):
    roles = ADMIN
    model, form_class, title, prefix = Part, forms.PartForm, 'Edit part', 'part'


class PartDelete(DeleteBase):
    model, prefix = Part, 'part'


# ---- bookings
class BookingList(ListBase):
    model = Booking
    title, prefix, has_detail = 'Bookings', 'booking', True
    id_search = True
    search_fields = ['car__registration_number', 'car__customer__name', 'car__brand', 'car__model', 'mechanic__name']
    columns = [('#', 'id'), ('Date', 'booking_date'), ('Car', 'car.registration_number'),
               ('Customer', 'car.customer.name'), ('Mechanic', 'mechanic.name'), ('Status', 'status'),
               ('Total', 'total'), ('Payment', 'payment_status')]
    filter_param, filter_label = 'status', 'Status'

    def get_queryset(self):
        return super().get_queryset().select_related('car', 'car__customer', 'mechanic')

    def get_filter_choices(self):
        return Booking.STATUS_CHOICES


class BookingCreate(CreateBase):
    model, form_class, title, prefix = Booking, forms.BookingForm, 'New booking', 'booking'
    success_message = "Booking created. Now add the services and parts."

    def get_success_url(self):
        return reverse('booking_detail', args=[self.object.pk])


class BookingUpdate(UpdateBase):
    model, form_class, title, prefix = Booking, forms.BookingForm, 'Edit booking', 'booking'

    def get_success_url(self):
        return reverse('booking_detail', args=[self.object.pk])


class BookingDelete(DeleteBase):
    model, prefix = Booking, 'booking'

    def delete_object(self, obj):
        if obj.payments.exists():
            raise ProtectedError("payments exist", set())
        if obj.status != Booking.CANCELLED:     # give reserved stock back
            _restore_stock(obj)
        obj.delete()


def _restore_stock(booking):
    for item in booking.part_items.all():
        Part.objects.filter(pk=item.part_id).update(stock_qty=F('stock_qty') + item.quantity)


# ---- payments (created from a booking page; list + delete here)
class PaymentList(ListBase):
    model = Payment
    title, prefix = 'Payments', 'payment'
    can_add = False
    can_edit = False
    search_fields = ['reference', 'booking__car__registration_number', 'booking__car__customer__name']
    columns = [('Paid on', 'paid_on'), ('Booking', 'booking.id'), ('Customer', 'booking.car.customer.name'),
               ('Amount', 'amount'), ('Method', 'method'), ('Reference', 'reference'), ('Status', 'status')]
    filter_param, filter_label = 'status', 'Status'

    def get_queryset(self):
        return super().get_queryset().select_related('booking', 'booking__car', 'booking__car__customer')

    def get_filter_choices(self):
        return Payment.STATUS_CHOICES


class PaymentDelete(DeleteBase):
    model, prefix = Payment, 'payment'


# ------------------------------------------------------------ booking detail
@role_required(*STAFF)
def booking_detail(request, pk):
    b = get_object_or_404(Booking.objects.select_related('car', 'car__customer', 'mechanic'), pk=pk)
    return render(request, 'services/booking_detail.html', {
        'b': b,
        'service_items': b.service_items.select_related('service', 'service__category'),
        'part_items': b.part_items.select_related('part'),
        'payments': b.payments.all(),
        'next_statuses': Booking.TRANSITIONS[b.status],
        'service_form': forms.AddServiceForm(booking=b),
        'part_form': forms.AddPartForm(booking=b),
        'payment_form': forms.PaymentForm(booking=b),
        'feedback_form': forms.FeedbackForm(),
        'totals': {'services': b.services_total, 'parts': b.parts_total, 'total': b.total,
                   'paid': b.paid_total, 'balance': b.balance, 'pending': b.pending_total,
                   'payable': b.payable},
    })


def _errors(form):
    return " ".join(f"{', '.join(errs)}" for errs in form.errors.values())


def _back(pk):
    return redirect('booking_detail', pk=pk)


@role_required(*STAFF)
@require_POST
def booking_add_service(request, pk):
    b = get_object_or_404(Booking, pk=pk)
    if not b.can_edit_items:
        messages.error(request, "This booking is closed; services can't be changed.")
        return _back(pk)
    form = forms.AddServiceForm(request.POST, booking=b)
    if form.is_valid():
        s = form.cleaned_data['service']
        BookingService.objects.create(booking=b, service=s, price=s.price)
        messages.success(request, f"Added service: {s.name}.")
    else:
        messages.error(request, _errors(form))
    return _back(pk)


def add_part_to_booking(request, b, data, show_price=True):
    """Shared by staff and mechanics: add a part line and deduct stock."""
    if not b.can_edit_items:
        messages.error(request, "This booking is closed; parts can't be changed.")
        return False
    form = forms.AddPartForm(data, booking=b, show_price=show_price)
    if not form.is_valid():
        messages.error(request, _errors(form))
        return False
    p, qty = form.cleaned_data['part'], form.cleaned_data['quantity']
    with transaction.atomic():
        BookingPart.objects.create(booking=b, part=p, quantity=qty, unit_price=p.unit_price)
        Part.objects.filter(pk=p.pk).update(stock_qty=F('stock_qty') - qty)
    messages.success(request, f"Added {qty} x {p.name}. Stock updated.")
    return True


@role_required(*STAFF)
@require_POST
def booking_add_part(request, pk):
    b = get_object_or_404(Booking, pk=pk)
    add_part_to_booking(request, b, request.POST)
    return _back(pk)


@role_required(*STAFF)
@require_POST
def booking_remove_service(request, pk, item_pk):
    b = get_object_or_404(Booking, pk=pk)
    if b.can_edit_items:
        get_object_or_404(BookingService, pk=item_pk, booking=b).delete()
        messages.success(request, "Service removed.")
    else:
        messages.error(request, "This booking is closed.")
    return _back(pk)


@role_required(*STAFF)
@require_POST
def booking_remove_part(request, pk, item_pk):
    b = get_object_or_404(Booking, pk=pk)
    if not b.can_edit_items:
        messages.error(request, "This booking is closed.")
        return _back(pk)
    item = get_object_or_404(BookingPart, pk=item_pk, booking=b)
    with transaction.atomic():
        Part.objects.filter(pk=item.part_id).update(stock_qty=F('stock_qty') + item.quantity)
        item.delete()
    messages.success(request, "Part removed and stock restored.")
    return _back(pk)


def apply_status(request, b, new):
    """Shared by staff, mechanics and customers: enforce the workflow and apply a status change."""
    if new not in Booking.TRANSITIONS[b.status]:
        messages.error(request, f"Can't move a {b.status} booking to {new}.")
    elif new == Booking.IN_PROGRESS and not b.mechanic_id:
        messages.error(request, "Assign a mechanic (Edit booking) before starting the job.")
    elif new == Booking.COMPLETED and not b.service_items.exists():
        messages.error(request, "Add at least one service before completing the booking.")
    else:
        with transaction.atomic():
            if new == Booking.CANCELLED:
                _restore_stock(b)
            b.status = new
            b.save(update_fields=['status'])
        messages.success(request, f"Booking marked {new}.")
        return True
    return False


@role_required(*STAFF)
@require_POST
def booking_set_status(request, pk):
    b = get_object_or_404(Booking, pk=pk)
    apply_status(request, b, request.POST.get('status'))
    return _back(pk)


@role_required(*STAFF)
@require_POST
def booking_add_payment(request, pk):
    b = get_object_or_404(Booking, pk=pk)
    if b.status == Booking.CANCELLED:
        messages.error(request, "Can't take payment on a cancelled booking.")
        return _back(pk)
    form = forms.PaymentForm(request.POST, booking=b)
    if form.is_valid():
        Payment.objects.create(booking=b, status=Payment.CONFIRMED, verified_by=request.user,
                               verified_at=timezone.now(), **form.cleaned_data)
        messages.success(request, "Payment recorded.")
    else:
        messages.error(request, _errors(form))
    return _back(pk)


@role_required(*STAFF)
@require_POST
def booking_feedback(request, pk):
    b = get_object_or_404(Booking, pk=pk)
    form = forms.FeedbackForm(request.POST)
    if b.status != Booking.COMPLETED:
        messages.error(request, "Feedback can only be added once the job is completed.")
    elif form.is_valid():
        Feedback.objects.update_or_create(booking=b, defaults=form.cleaned_data)
        messages.success(request, "Feedback saved.")
    else:
        messages.error(request, _errors(form))
    return _back(pk)


@role_required(*STAFF)
@require_POST
def batch_verify(request, pk):
    """Staff confirm (money seen in the bank) or reject a UPI transaction a customer submitted.
    A batch can cover several invoices; it is confirmed or rejected as a whole (all-or-nothing)."""
    batch = get_object_or_404(PaymentBatch.objects.prefetch_related('payments__booking'), pk=pk)
    action = request.POST.get('action')
    with transaction.atomic():
        if batch.status != 'Pending':
            messages.error(request, "That payment has already been processed.")
        elif action == 'confirm':
            over = [p.booking_id for p in batch.payments.all() if p.amount > p.booking.balance]
            if over:
                messages.error(request, "Can't confirm: it would overpay booking "
                                        + ", ".join(f"#{i}" for i in over) + ". Reject it instead.")
            else:
                _settle(batch, 'Confirmed', request.user)
                messages.success(request, f"Payment of Rs {batch.total_amount:.0f} confirmed.")
        elif action == 'reject':
            _settle(batch, 'Rejected', request.user)
            messages.success(request, "Payment rejected. The customer can submit it again.")
        else:
            messages.error(request, "Unknown action.")
    nxt = request.POST.get('next', '')
    if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        nxt = reverse('payment_list')
    return redirect(nxt)


def _settle(batch, status, user):
    now = timezone.now()
    batch.status, batch.verified_by, batch.verified_at = status, user, now
    batch.save(update_fields=['status', 'verified_by', 'verified_at'])
    batch.payments.update(status=status, verified_by=user, verified_at=now)


# -------------------------------------------------------------------- reports
@role_required(*ADMIN)
def reports(request):
    results = []
    with connection.cursor() as cur:
        for r in REPORTS:
            cur.execute(r['sql'])
            cols = [c[0] for c in cur.description]
            results.append({**r, 'cols': cols, 'rows': cur.fetchall()})
    return render(request, 'services/reports.html', {'reports': results})
