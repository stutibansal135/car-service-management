from django.contrib import admin

from .models import (Booking, BookingPart, BookingService, Car, Customer, Feedback,
                     Mechanic, Part, Payment, PaymentBatch, Profile, Service, ServiceCategory, Supplier)

admin.site.site_header = "CSM | Administration"
admin.site.site_title = "Car Service Management"
admin.site.index_title = "Management Control Centre"


class CSMAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("admin_custom.css",)}


@admin.register(Customer)
class CustomerAdmin(CSMAdmin):
    list_display = ("id", "name", "phone", "email", "city")
    search_fields = ("name", "phone", "email")
    list_filter = ("city",)


@admin.register(Supplier)
class SupplierAdmin(CSMAdmin):
    list_display = ("id", "name", "phone", "city")
    search_fields = ("name",)


@admin.register(Car)
class CarAdmin(CSMAdmin):
    list_display = ("id", "registration_number", "brand", "model", "year", "fuel_type", "customer")
    search_fields = ("brand", "model", "registration_number", "customer__name")
    list_filter = ("brand", "fuel_type")


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(CSMAdmin):
    list_display = ("id", "name")


@admin.register(Service)
class ServiceAdmin(CSMAdmin):
    list_display = ("id", "name", "category", "price", "duration_minutes", "is_active")
    search_fields = ("name",)
    list_filter = ("category", "is_active")


@admin.register(Mechanic)
class MechanicAdmin(CSMAdmin):
    list_display = ("id", "name", "phone", "specialization", "is_active")
    list_filter = ("specialization", "is_active")


@admin.register(Part)
class PartAdmin(CSMAdmin):
    list_display = ("id", "sku", "name", "supplier", "unit_price", "stock_qty", "reorder_level")
    search_fields = ("name", "sku")
    list_filter = ("supplier",)


class BookingServiceInline(admin.TabularInline):
    model = BookingService
    extra = 0


class BookingPartInline(admin.TabularInline):
    model = BookingPart
    extra = 0


@admin.register(Booking)
class BookingAdmin(CSMAdmin):
    list_display = ("id", "car", "mechanic", "booking_date", "status")
    list_filter = ("status", "booking_date", "mechanic")
    search_fields = ("car__registration_number", "car__customer__name")
    inlines = [BookingServiceInline, BookingPartInline]


@admin.register(Payment)
class PaymentAdmin(CSMAdmin):
    list_display = ("id", "booking", "amount", "method", "status", "paid_on")
    list_filter = ("status", "method", "paid_on")


@admin.register(Feedback)
class FeedbackAdmin(CSMAdmin):
    list_display = ("id", "booking", "rating")
    list_filter = ("rating",)


@admin.register(Profile)
class ProfileAdmin(CSMAdmin):
    list_display = ("user", "role", "customer", "mechanic")
    list_filter = ("role",)


@admin.register(PaymentBatch)
class PaymentBatchAdmin(CSMAdmin):
    list_display = ("id", "customer", "reference", "total_amount", "status", "created_on")
    list_filter = ("status",)
    search_fields = ("reference", "customer__name")
