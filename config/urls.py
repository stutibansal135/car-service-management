from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from services import portal as pt
from services import views as v

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', v.home, name='home'),
    path('login/', auth_views.LoginView.as_view(redirect_authenticated_user=True), name='login'),
    path('signup/', pt.signup, name='signup'),
    path('about/', pt.about, name='about'),
    path('track/', pt.track, name='track'),
    path('go/', pt.after_login, name='after_login'),
    path('account/', pt.account, name='account'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('dashboard/', v.dashboard, name='dashboard'),
    path('reports/', v.reports, name='reports'),

    path('customers/', v.CustomerList.as_view(), name='customer_list'),
    path('customers/add/', v.CustomerCreate.as_view(), name='customer_add'),
    path('customers/<int:pk>/', v.customer_detail, name='customer_detail'),
    path('customers/<int:pk>/edit/', v.CustomerUpdate.as_view(), name='customer_edit'),
    path('customers/<int:pk>/delete/', v.CustomerDelete.as_view(), name='customer_delete'),

    path('cars/', v.CarList.as_view(), name='car_list'),
    path('cars/add/', v.CarCreate.as_view(), name='car_add'),
    path('cars/<int:pk>/edit/', v.CarUpdate.as_view(), name='car_edit'),
    path('cars/<int:pk>/delete/', v.CarDelete.as_view(), name='car_delete'),

    path('services/', v.ServiceList.as_view(), name='service_list'),
    path('services/add/', v.ServiceCreate.as_view(), name='service_add'),
    path('services/<int:pk>/edit/', v.ServiceUpdate.as_view(), name='service_edit'),
    path('services/<int:pk>/delete/', v.ServiceDelete.as_view(), name='service_delete'),

    path('mechanics/', v.MechanicList.as_view(), name='mechanic_list'),
    path('mechanics/add/', v.MechanicCreate.as_view(), name='mechanic_add'),
    path('mechanics/<int:pk>/edit/', v.MechanicUpdate.as_view(), name='mechanic_edit'),
    path('mechanics/<int:pk>/delete/', v.MechanicDelete.as_view(), name='mechanic_delete'),

    path('suppliers/', v.SupplierList.as_view(), name='supplier_list'),
    path('suppliers/add/', v.SupplierCreate.as_view(), name='supplier_add'),
    path('suppliers/<int:pk>/edit/', v.SupplierUpdate.as_view(), name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', v.SupplierDelete.as_view(), name='supplier_delete'),

    path('parts/', v.PartList.as_view(), name='part_list'),
    path('parts/add/', v.PartCreate.as_view(), name='part_add'),
    path('parts/<int:pk>/edit/', v.PartUpdate.as_view(), name='part_edit'),
    path('parts/<int:pk>/delete/', v.PartDelete.as_view(), name='part_delete'),

    path('bookings/', v.BookingList.as_view(), name='booking_list'),
    path('bookings/add/', v.BookingCreate.as_view(), name='booking_add'),
    path('bookings/<int:pk>/', v.booking_detail, name='booking_detail'),
    path('bookings/<int:pk>/edit/', v.BookingUpdate.as_view(), name='booking_edit'),
    path('bookings/<int:pk>/delete/', v.BookingDelete.as_view(), name='booking_delete'),
    path('bookings/<int:pk>/add-service/', v.booking_add_service, name='booking_add_service'),
    path('bookings/<int:pk>/add-part/', v.booking_add_part, name='booking_add_part'),
    path('bookings/<int:pk>/remove-service/<int:item_pk>/', v.booking_remove_service, name='booking_remove_service'),
    path('bookings/<int:pk>/remove-part/<int:item_pk>/', v.booking_remove_part, name='booking_remove_part'),
    path('bookings/<int:pk>/status/', v.booking_set_status, name='booking_set_status'),
    path('bookings/<int:pk>/add-payment/', v.booking_add_payment, name='booking_add_payment'),
    path('bookings/<int:pk>/feedback/', v.booking_feedback, name='booking_feedback'),
    path('bookings/<int:pk>/invoice/', pt.invoice, name='invoice'),

    path('payments/', v.PaymentList.as_view(), name='payment_list'),
    path('payments/<int:pk>/delete/', v.PaymentDelete.as_view(), name='payment_delete'),
    path('payments/batch/<int:pk>/verify/', v.batch_verify, name='batch_verify'),

    # ---- customer portal
    path('portal/', pt.portal_home, name='portal_home'),
    path('portal/cars/', pt.PortalCarList.as_view(), name='portal_cars'),
    path('portal/cars/add/', pt.PortalCarCreate.as_view(), name='portal_car_add'),
    path('portal/cars/<int:pk>/edit/', pt.PortalCarUpdate.as_view(), name='portal_car_edit'),
    path('portal/book/', pt.portal_book_new, name='portal_book_new'),
    path('portal/bookings/', pt.PortalBookingList.as_view(), name='portal_bookings'),
    path('portal/bookings/<int:pk>/', pt.portal_booking_detail, name='portal_booking_detail'),
    path('portal/bookings/<int:pk>/invoice/', pt.portal_invoice, name='portal_invoice'),
    path('portal/bookings/<int:pk>/cancel/', pt.portal_booking_cancel, name='portal_booking_cancel'),
    path('portal/bookings/<int:pk>/pay/', pt.portal_booking_pay, name='portal_booking_pay'),
    path('portal/bookings/<int:pk>/feedback/', pt.portal_booking_feedback, name='portal_booking_feedback'),
    path('portal/payments/', pt.portal_payments, name='portal_payments'),
    path('portal/pay/', pt.portal_pay_multi, name='portal_pay_multi'),
    path('portal/pay/submit/', pt.portal_pay_multi_submit, name='portal_pay_multi_submit'),
    path('portal/bookings/<int:pk>/checkout/', pt.portal_pay_checkout, name='portal_pay_checkout'),
    path('portal/bookings/<int:pk>/upi/', pt.portal_pay_upi, name='portal_pay_upi'),

    # ---- mechanic portal
    path('mechanic/', pt.mech_home, name='mech_home'),
    path('mechanic/jobs/', pt.MechJobList.as_view(), name='mech_jobs'),
    path('mechanic/jobs/<int:pk>/', pt.mech_job_detail, name='mech_job_detail'),
    path('mechanic/jobs/<int:pk>/status/', pt.mech_job_status, name='mech_job_status'),
    path('mechanic/jobs/<int:pk>/add-part/', pt.mech_job_add_part, name='mech_job_add_part'),
    path('mechanic/jobs/<int:pk>/note/', pt.mech_job_note, name='mech_job_note'),
]
