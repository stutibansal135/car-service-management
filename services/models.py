from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Sum

phone_validator = RegexValidator(r'^[6-9]\d{9}$', 'Enter a valid 10-digit Indian mobile number.')
reg_validator = RegexValidator(
    r'^[A-Z]{2}\d{2}[A-Z]{1,3}\d{4}$',
    'Use the format PB10AB1234 (capital letters, no spaces or dashes).',
)


class Customer(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=10, unique=True, validators=[phone_validator])
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    city = models.CharField(max_length=60, default='Ludhiana')
    joined_on = models.DateField(default=date.today)

    class Meta:
        db_table = 'customer'
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def total_spent(self):
        return (Payment.objects.filter(booking__car__customer=self, status='Confirmed')
                .aggregate(t=Sum('amount'))['t'] or Decimal('0'))


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=10, validators=[phone_validator])
    email = models.EmailField(blank=True)
    city = models.CharField(max_length=60)

    class Meta:
        db_table = 'supplier'
        ordering = ['name']

    def __str__(self):
        return self.name


class Car(models.Model):
    FUEL_CHOICES = [('Petrol', 'Petrol'), ('Diesel', 'Diesel'), ('CNG', 'CNG'), ('Electric', 'Electric')]

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='cars')
    brand = models.CharField(max_length=50)
    model = models.CharField(max_length=50)
    year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1990), MaxValueValidator(2100)])
    fuel_type = models.CharField(max_length=10, choices=FUEL_CHOICES, default='Petrol')
    color = models.CharField(max_length=30, blank=True)
    registration_number = models.CharField(max_length=15, unique=True, validators=[reg_validator])

    class Meta:
        db_table = 'car'
        ordering = ['registration_number']
        constraints = [models.CheckConstraint(condition=models.Q(year__gte=1990), name='car_year_gte_1990')]

    def __str__(self):
        return f"{self.registration_number} - {self.brand} {self.model}"

    @property
    def full_name(self):
        return f"{self.brand} {self.model} ({self.year})"


class ServiceCategory(models.Model):
    name = models.CharField(max_length=60, unique=True)

    class Meta:
        db_table = 'service_category'
        verbose_name_plural = 'service categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class Service(models.Model):
    category = models.ForeignKey(ServiceCategory, on_delete=models.PROTECT, related_name='services')
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    duration_minutes = models.PositiveIntegerField(default=60)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'service'
        ordering = ['category__name', 'name']
        constraints = [models.CheckConstraint(condition=models.Q(price__gte=0), name='service_price_gte_0')]

    def __str__(self):
        return self.name


class Mechanic(models.Model):
    name = models.CharField(max_length=100)
    phone = models.CharField(max_length=10, unique=True, validators=[phone_validator])
    specialization = models.ForeignKey(
        ServiceCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='mechanics')
    hire_date = models.DateField(default=date.today)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'mechanic'
        ordering = ['name']

    def __str__(self):
        return self.name


class Part(models.Model):
    sku = models.CharField('SKU', max_length=30, unique=True)
    name = models.CharField(max_length=120)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='parts')
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    stock_qty = models.PositiveIntegerField(default=0)
    reorder_level = models.PositiveIntegerField(default=10)

    class Meta:
        db_table = 'part'
        ordering = ['name']
        constraints = [models.CheckConstraint(condition=models.Q(unit_price__gte=0), name='part_price_gte_0')]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    @property
    def stock_status(self):
        if self.stock_qty == 0:
            return 'Out of stock'
        if self.stock_qty <= self.reorder_level:
            return 'Low stock'
        return 'In stock'


class Booking(models.Model):
    PENDING, IN_PROGRESS, COMPLETED, CANCELLED = 'Pending', 'In Progress', 'Completed', 'Cancelled'
    STATUS_CHOICES = [(s, s) for s in (PENDING, IN_PROGRESS, COMPLETED, CANCELLED)]
    # allowed workflow moves; Completed and Cancelled are final
    TRANSITIONS = {
        PENDING: [IN_PROGRESS, CANCELLED],
        IN_PROGRESS: [COMPLETED, CANCELLED],
        COMPLETED: [],
        CANCELLED: [],
    }

    car = models.ForeignKey(Car, on_delete=models.PROTECT, related_name='bookings')
    mechanic = models.ForeignKey(Mechanic, on_delete=models.SET_NULL, null=True, blank=True, related_name='bookings')
    booking_date = models.DateField()
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=PENDING)
    odometer_km = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'booking'
        ordering = ['-booking_date', '-id']
        indexes = [models.Index(fields=['status']), models.Index(fields=['booking_date'])]

    def __str__(self):
        return f"Booking #{self.pk} - {self.car.registration_number}"

    @property
    def customer(self):
        return self.car.customer

    @property
    def services_total(self):
        return self.service_items.aggregate(t=Sum('price'))['t'] or Decimal('0')

    @property
    def parts_total(self):
        return sum((i.line_total for i in self.part_items.all()), Decimal('0'))

    @property
    def total(self):
        return self.services_total + self.parts_total

    @property
    def paid_total(self):
        """Money actually received: only Confirmed payments count."""
        return self.payments.filter(status='Confirmed').aggregate(t=Sum('amount'))['t'] or Decimal('0')

    @property
    def pending_total(self):
        """UPI payments the customer has submitted that staff haven't verified yet."""
        return self.payments.filter(status='Pending').aggregate(t=Sum('amount'))['t'] or Decimal('0')

    @property
    def balance(self):
        return self.total - self.paid_total

    @property
    def payable(self):
        """What can still be paid now: balance minus amounts already awaiting verification."""
        return max(self.balance - self.pending_total, Decimal('0'))

    @property
    def payment_status(self):
        if self.status == self.CANCELLED or self.total == 0:
            return '-'
        if self.balance <= 0:
            return 'Paid'
        if self.paid_total == 0:
            return 'Verifying' if self.pending_total > 0 else 'Unpaid'
        return 'Partial'

    @property
    def service_summary(self):
        return ", ".join(i.service.name for i in self.service_items.all()) or "-"

    @property
    def can_edit_items(self):
        return self.status in (self.PENDING, self.IN_PROGRESS)


class BookingService(models.Model):
    """Junction table Booking <-> Service. `price` is a snapshot so old invoices never change."""
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='service_items')
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='booking_items')
    price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'booking_service'
        constraints = [models.UniqueConstraint(fields=['booking', 'service'], name='uniq_booking_service')]


class BookingPart(models.Model):
    """Junction table Booking <-> Part with quantity and price snapshot."""
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='part_items')
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name='booking_items')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        db_table = 'booking_part'
        constraints = [
            models.UniqueConstraint(fields=['booking', 'part'], name='uniq_booking_part'),
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name='bookingpart_qty_gte_1'),
        ]

    @property
    def line_total(self):
        return self.quantity * self.unit_price


class PaymentBatch(models.Model):
    """One customer UPI transaction (one UTR). It can settle several bookings at once: each booking gets its
    own Payment row (the allocation) pointing back here. Staff confirm or reject the whole batch together."""
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='payment_batches')
    reference = models.CharField('UTR', max_length=12)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    status = models.CharField(max_length=10, choices=[('Confirmed', 'Confirmed'), ('Pending', 'Pending verification'),
                                                      ('Rejected', 'Rejected')], default='Pending')
    created_on = models.DateField(default=date.today)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='verified_batches')
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'payment_batch'
        ordering = ['created_on', 'id']
        indexes = [models.Index(fields=['status'])]
        constraints = [
            models.CheckConstraint(condition=models.Q(total_amount__gt=0), name='batch_total_gt_0'),
            models.CheckConstraint(condition=models.Q(status__in=['Confirmed', 'Pending', 'Rejected']),
                                   name='batch_status_valid'),
            # a UTR can only be claimed once (a rejected one may be submitted again)
            models.UniqueConstraint(fields=['reference'], condition=~models.Q(status='Rejected'),
                                    name='uniq_active_batch_utr'),
        ]

    def __str__(self):
        return f"Batch #{self.pk} - UTR {self.reference} - Rs {self.total_amount}"


class Payment(models.Model):
    METHOD_CHOICES = [('UPI', 'UPI'), ('Cash', 'Cash'), ('Card', 'Card'), ('Net Banking', 'Net Banking')]
    CONFIRMED, PENDING, REJECTED = 'Confirmed', 'Pending', 'Rejected'
    STATUS_CHOICES = [(CONFIRMED, 'Confirmed'), (PENDING, 'Pending verification'), (REJECTED, 'Rejected')]

    booking = models.ForeignKey(Booking, on_delete=models.PROTECT, related_name='payments')
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    method = models.CharField(max_length=15, choices=METHOD_CHOICES, default='UPI')
    paid_on = models.DateField(default=date.today)
    reference = models.CharField('Transaction ref / UTR', max_length=40, blank=True)
    # customer-submitted UPI payments start as Pending until staff see the money in the bank
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=CONFIRMED)
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='verified_payments')
    verified_at = models.DateTimeField(null=True, blank=True)
    # set when the customer paid several invoices with one UPI transaction
    batch = models.ForeignKey(PaymentBatch, on_delete=models.PROTECT, null=True, blank=True, related_name='payments')

    class Meta:
        db_table = 'payment'
        ordering = ['-paid_on', '-id']
        indexes = [models.Index(fields=['paid_on']), models.Index(fields=['status'])]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='payment_amount_gt_0'),
            models.CheckConstraint(condition=models.Q(status__in=['Confirmed', 'Pending', 'Rejected']),
                                   name='payment_status_valid'),
            # a UPI reference typed in by staff can't be reused (batch payments are guarded by payment_batch instead,
            # because several rows of one batch legitimately share the same UTR)
            models.UniqueConstraint(fields=['reference'], name='uniq_active_upi_reference',
                                    condition=models.Q(method='UPI') & ~models.Q(reference='')
                                    & ~models.Q(status='Rejected') & models.Q(batch__isnull=True)),
        ]

    def __str__(self):
        return f"Payment #{self.pk} - Rs {self.amount}"


class Feedback(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='feedback')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)

    class Meta:
        db_table = 'feedback'
        constraints = [models.CheckConstraint(
            condition=models.Q(rating__gte=1, rating__lte=5), name='feedback_rating_1_5')]


class Profile(models.Model):
    """Links a login account to a role, and (for customers / mechanics) to their record."""
    ROLE_CHOICES = [('admin', 'Admin / Owner'), ('staff', 'Staff / Receptionist'),
                    ('mechanic', 'Mechanic'), ('customer', 'Customer')]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    customer = models.OneToOneField(Customer, on_delete=models.CASCADE, null=True, blank=True, related_name='profile')
    mechanic = models.OneToOneField(Mechanic, on_delete=models.CASCADE, null=True, blank=True, related_name='profile')

    class Meta:
        db_table = 'user_profile'
        constraints = [
            # a customer login must point at a customer, a mechanic login at a mechanic
            models.CheckConstraint(condition=~models.Q(role='customer') | models.Q(customer__isnull=False),
                                   name='profile_customer_needs_customer'),
            models.CheckConstraint(condition=~models.Q(role='mechanic') | models.Q(mechanic__isnull=False),
                                   name='profile_mechanic_needs_mechanic'),
        ]

    def __str__(self):
        return f"{self.user} ({self.role})"
