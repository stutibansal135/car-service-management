from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordChangeForm
from django.core.validators import RegexValidator
from django.contrib.auth.password_validation import validate_password

from .models import (Booking, Car, Customer, Feedback, Mechanic, Part, Payment, Service, Supplier,
                     phone_validator)

INPUT = ("w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 "
         "focus:border-gold focus:ring-2 focus:ring-gold/30 focus:outline-none")
CHECK = "h-4 w-4 rounded border-slate-300 text-navy focus:ring-gold"


class StyledForm(forms.ModelForm):
    """Adds Tailwind classes to every widget."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


def style_fields(form):
    for f in form.fields.values():
        cls = CHECK if isinstance(f.widget, forms.CheckboxInput) else INPUT
        f.widget.attrs['class'] = (f.widget.attrs.get('class', '') + ' ' + cls).strip()
        if isinstance(f.widget, forms.Textarea):
            f.widget.attrs['rows'] = 3


class StyledPlainForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)


class DateInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, **kw):
        super().__init__(format='%Y-%m-%d', **kw)


class CustomerForm(StyledForm):
    class Meta:
        model = Customer
        fields = ['name', 'phone', 'email', 'city', 'address']
        widgets = {'phone': forms.TextInput(attrs={'placeholder': '10-digit mobile', 'maxlength': 10})}


class SupplierForm(StyledForm):
    class Meta:
        model = Supplier
        fields = ['name', 'phone', 'email', 'city']


class CarForm(StyledForm):
    class Meta:
        model = Car
        fields = ['customer', 'registration_number', 'brand', 'model', 'year', 'fuel_type', 'color']
        widgets = {'registration_number': forms.TextInput(attrs={'placeholder': 'PB10AB1234'})}

    def clean_registration_number(self):
        return self.cleaned_data['registration_number'].upper().replace(' ', '').replace('-', '')


class ServiceForm(StyledForm):
    class Meta:
        model = Service
        fields = ['category', 'name', 'price', 'duration_minutes', 'description', 'is_active']


class MechanicForm(StyledForm):
    class Meta:
        model = Mechanic
        fields = ['name', 'phone', 'specialization', 'hire_date', 'is_active']
        widgets = {'hire_date': DateInput()}


class PartForm(StyledForm):
    class Meta:
        model = Part
        fields = ['sku', 'name', 'supplier', 'unit_price', 'stock_qty', 'reorder_level']


class CarChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, car):
        return f"{car.registration_number} - {car.brand} {car.model} ({car.customer.name})"


class BookingForm(StyledForm):
    car = CarChoiceField(queryset=Car.objects.select_related('customer').order_by('registration_number'))
    mechanic = forms.ModelChoiceField(queryset=Mechanic.objects.filter(is_active=True), required=False,
                                      empty_label='- assign later -')

    class Meta:
        model = Booking
        fields = ['car', 'mechanic', 'booking_date', 'odometer_km', 'notes']
        widgets = {'booking_date': DateInput()}

    def clean_booking_date(self):
        d = self.cleaned_data['booking_date']
        if not self.instance.pk and d < date.today():
            raise forms.ValidationError("New bookings can't be in the past.")
        return d


class AddServiceForm(StyledPlainForm):
    service = forms.ModelChoiceField(queryset=Service.objects.filter(is_active=True).select_related('category'))

    def __init__(self, *args, booking=None, **kwargs):
        super().__init__(*args, **kwargs)
        if booking is not None:
            self.fields['service'].queryset = self.fields['service'].queryset.exclude(booking_items__booking=booking)
        self.fields['service'].label_from_instance = lambda s: f"{s.category.name} - {s.name} (Rs {s.price:.0f})"


class AddPartForm(StyledPlainForm):
    part = forms.ModelChoiceField(queryset=Part.objects.filter(stock_qty__gt=0))
    quantity = forms.IntegerField(min_value=1, initial=1)

    def __init__(self, *args, booking=None, show_price=True, **kwargs):
        super().__init__(*args, **kwargs)
        if booking is not None:
            self.fields['part'].queryset = self.fields['part'].queryset.exclude(booking_items__booking=booking)
        if show_price:
            self.fields['part'].label_from_instance = lambda p: f"{p.name} - Rs {p.unit_price:.0f} ({p.stock_qty} in stock)"
        else:
            self.fields['part'].label_from_instance = lambda p: f"{p.name} ({p.stock_qty} in stock)"

    def clean(self):
        data = super().clean()
        part, qty = data.get('part'), data.get('quantity')
        if part and qty and qty > part.stock_qty:
            self.add_error('quantity', f"Only {part.stock_qty} in stock.")
        return data


class PaymentForm(StyledPlainForm):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=Payment.METHOD_CHOICES)
    paid_on = forms.DateField(widget=DateInput(), initial=date.today)
    reference = forms.CharField(max_length=40, required=False, label='Transaction ref')

    def __init__(self, *args, booking=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.booking = booking
        if booking is not None and not self.is_bound:
            self.fields['amount'].initial = booking.payable

    def clean_amount(self):
        return check_payable(self.cleaned_data['amount'], self.booking)


def check_payable(amount, booking):
    """Amount must not exceed what is still payable (balance minus UPI payments awaiting verification)."""
    if booking is not None and amount > booking.payable:
        msg = f"Amount exceeds what is still payable (Rs {booking.payable:.2f})."
        if booking.pending_total:
            msg += f" Rs {booking.pending_total:.2f} is already awaiting verification."
        raise forms.ValidationError(msg)
    return amount


class FeedbackForm(StyledPlainForm):
    rating = forms.TypedChoiceField(choices=[(i, f"{i} star{'s' if i > 1 else ''}") for i in range(5, 0, -1)],
                                    coerce=int)
    comment = forms.CharField(required=False, widget=forms.Textarea)


# ------------------------------------------------------------ customer portal / public
class PortalCarForm(StyledForm):
    class Meta:
        model = Car
        fields = ['registration_number', 'brand', 'model', 'year', 'fuel_type', 'color']
        widgets = {'registration_number': forms.TextInput(attrs={'placeholder': 'PB10AB1234'})}

    def clean_registration_number(self):
        return self.cleaned_data['registration_number'].upper().replace(' ', '').replace('-', '')


class BookServiceForm(StyledPlainForm):
    car = forms.ModelChoiceField(queryset=Car.objects.none())
    booking_date = forms.DateField(widget=DateInput(), label='Preferred date')
    services = forms.ModelMultipleChoiceField(queryset=Service.objects.filter(is_active=True),
                                              widget=forms.CheckboxSelectMultiple,
                                              error_messages={'required': 'Pick at least one service.'})
    notes = forms.CharField(required=False, widget=forms.Textarea, label='Anything we should know?')

    def __init__(self, *args, customer=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['car'].queryset = Car.objects.filter(customer=customer)
        self.fields['car'].label_from_instance = lambda c: f"{c.registration_number} - {c.brand} {c.model}"

    def clean_booking_date(self):
        d = self.cleaned_data['booking_date']
        if d < date.today():
            raise forms.ValidationError("Please choose today or a future date.")
        return d


class DemoPayForm(StyledPlainForm):
    """Demo card / net-banking checkout (UPI has its own real flow below)."""
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=[('Card', 'Card'), ('Net Banking', 'Net Banking')])

    def __init__(self, *args, booking=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.booking = booking
        if booking is not None and not self.is_bound:
            self.fields['amount'].initial = booking.payable

    def clean_amount(self):
        return check_payable(self.cleaned_data['amount'], self.booking)


class UtrForm(StyledPlainForm):
    """The 12-digit UPI transaction ID the customer copies from their UPI app."""
    utr = forms.CharField(label='UPI transaction ID (UTR)', max_length=12, min_length=12,
                          validators=[RegexValidator(r'^\d{12}$', 'The UTR is exactly 12 digits.')],
                          widget=forms.TextInput(attrs={'inputmode': 'numeric', 'placeholder': '12-digit number',
                                                        'maxlength': 12}))

    def clean_utr(self):
        utr = self.cleaned_data['utr'].strip()
        if Payment.objects.filter(method='UPI', reference=utr).exclude(status='Rejected').exists():
            raise forms.ValidationError("This transaction ID has already been submitted.")
        return utr


class UpiSubmitForm(UtrForm):
    """Pay ONE invoice (possibly part of it) by UPI."""
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01, widget=forms.HiddenInput)

    def __init__(self, *args, booking=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.booking = booking

    def clean_amount(self):
        return check_payable(self.cleaned_data['amount'], self.booking)


class MechanicNoteForm(StyledPlainForm):
    note = forms.CharField(max_length=300)


class SignupForm(StyledPlainForm):
    name = forms.CharField(max_length=100, label='Full name')
    phone = forms.CharField(max_length=10, validators=[phone_validator], label='Mobile number')
    email = forms.EmailField(required=False)
    username = forms.CharField(max_length=30)
    password = forms.CharField(widget=forms.PasswordInput)
    confirm_password = forms.CharField(widget=forms.PasswordInput)

    def clean_username(self):
        u = self.cleaned_data['username'].strip()
        if get_user_model().objects.filter(username__iexact=u).exists():
            raise forms.ValidationError("That username is taken.")
        return u

    def clean_phone(self):
        p = self.cleaned_data['phone']
        if Customer.objects.filter(phone=p).exists():
            raise forms.ValidationError("This number is already registered with the workshop. "
                                        "Ask the front desk to link it to a login.")
        return p

    def clean(self):
        data = super().clean()
        pw, pw2 = data.get('password'), data.get('confirm_password')
        if pw and pw2 and pw != pw2:
            self.add_error('confirm_password', "Passwords don't match.")
        elif pw:
            try:
                validate_password(pw)
            except forms.ValidationError as e:
                self.add_error('password', e)
        return data


# --------------------------------------------------------- "My account" (every role)
class UserDetailsForm(StyledForm):
    """Staff / admin edit their own name and email."""
    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']


class MechanicSelfForm(StyledForm):
    """A mechanic may change name and phone; speciality and hire date are managed by the admin."""
    class Meta:
        model = Mechanic
        fields = ['name', 'phone']


class PasswordForm(PasswordChangeForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        style_fields(self)
