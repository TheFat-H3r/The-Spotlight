from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from stores.models import Store
from .models import Booking, Order


# ==========================================
# 1. CUSTOMER VIEWS (Placing & Viewing History)
# ==========================================

@login_required
def customer_orders_list(request):
  
  my_orders = Order.objects.filter(user=request.user).order_by('-created_at')
  context = {'orders': my_orders}
  return render(request, 'transactions/customer_orders.html', context)


@login_required
def customer_bookings_list(request):
  
  my_bookings = Booking.objects.filter(user=request.user).order_by('-booking_date')
  context = {'bookings': my_bookings}
  return render(request, 'transactions/customer_bookings.html', context)


@login_required
def create_order(request, store_slug):
  
  store = Store.objects.filter(slug=store_slug, status=Store.Status.ACTIVE).first()
  if not store or not store.accepts_orders:
    return redirect('stores-home')

  if request.method == 'POST':
    # Extract order payload / amount from form submission
    total_amount = request.POST.get('total_amount', 0.00)
    
    Order.objects.create(
        user=request.user,
        store=store,
        total_amount=total_amount,
        status='Pending'
    )
    return redirect('customer-orders')

  context = {'store': store}
  return render(request, 'transactions/create_order.html', context)


@login_required
def create_booking(request, store_slug):
  
  store = Store.objects.filter(slug=store_slug, status=Store.Status.ACTIVE).first()
  if not store or not store.accepts_bookings:
    return redirect('stores-home')

  if request.method == 'POST':
    service_id = request.POST.get('service_id')
    booking_date = request.POST.get('booking_date')

    Booking.objects.create(
        user=request.user,
        store=store,
        service_id=service_id,
        booking_date=booking_date,
        status='Pending'
    )
    return redirect('customer-bookings')

  context = {'store': store}
  return render(request, 'transactions/create_booking.html', context)


# ==========================================
# 2. BUSINESS OWNER VIEWS (Fulfillment & Management)
# ==========================================

@login_required
def owner_orders_list(request):
  
  store = Store.objects.filter(vendor__user=request.user).first()
  if not store:
    return redirect('store-dashboard')

  orders = Order.objects.filter(store=store).order_by('-created_at')
  context = {'store': store, 'orders': orders}
  return render(request, 'transactions/owner_orders.html', context)


@login_required
def owner_bookings_list(request):
  
  store = Store.objects.filter(vendor__user=request.user).first()
  if not store:
    return redirect('store-dashboard')

  bookings = Booking.objects.filter(store=store).order_by('-booking_date')
  context = {'store': store, 'bookings': bookings}
  return render(request, 'transactions/owner_bookings.html', context)


@login_required
def update_order_status(request, order_id):
  
  order = Order.objects.filter(id=order_id, store__vendor__user=request.user).first()
  if not order:
    return redirect('store-dashboard')

  if request.method == 'POST':
    new_status = request.POST.get('status')
    if new_status:
      order.status = new_status
      order.save(update_fields=['status'])

  return redirect('owner-orders')


@login_required
def update_booking_status(request, booking_id):
  
  booking = Booking.objects.filter(id=booking_id, store__vendor__user=request.user).first()
  if not booking:
    return redirect('store-dashboard')

  if request.method == 'POST':
    new_status = request.POST.get('status')
    if new_status:
      booking.status = new_status
      booking.save(update_fields=['status'])

  return redirect('owner-bookings')