from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .models import Store, Product, Service, Review


def stores_home(request):
  
  return render(request, 'stores/home.html')


def store(request, slug):
  filtered_store = Store.objects.filter(slug=slug).first()
  store_reviews = Review.objects.filter(store=filtered_store)
  store_services = None
  store_products = None

  if filtered_store.business_type.store_type == "products":
    store_products = Product.objects.filter(store=filtered_store)

  elif filtered_store.business_type.store_type == "services":
    store_services = Service.objects.filter(store=filtered_store)

  else:
    store_services = Service.objects.filter(store=filtered_store)
    store_products = Product.objects.filter(store=filtered_store)

  context = {
      'store': filtered_store,
      'store_reviews': store_reviews,
  }

  if store_products is not None:
      context['store_products'] = store_products

  if store_services is not None:
      context['store_services'] = store_services

  return render(request, 'stores/store_detail.html', context)


@login_required
def store_dashboard(request):
  
  user_store = (
      Store.objects.filter(owner=request.user).first()
      if hasattr(request.user, 'vendor_profile')
      else None
  )

  context = {
      'store': user_store,
  }
  return render(request, 'stores/store_dashboard.html', context)


@login_required
def store_create(request):
  
  
  return render(request, 'stores/store_form.html')


@login_required
def store_update(request, slug):
  
  return render(request, 'stores/store_form.html')


@login_required
def store_delete(request, slug):
  
  return render(request, 'stores/store_confirm_delete.html')


@login_required
def store_toggle_orders(request, slug):
  """Operational helper function to toggle order acceptance on/off."""
  filtered_store = Store.objects.filter(
      slug=slug, owner=request.user
  ).first()

  if filtered_store:
    filtered_store.is_accepting_orders = not filtered_store.is_accepting_orders
    filtered_store.save(update_fields=['is_accepting_orders'])

  return redirect('store-dashboard')

def product_detail(request, id):
  return render(request, 'stores/product_detail.html')