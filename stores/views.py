from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from .models import Store


def stores_home(request):
  
  return render(request, 'stores/home.html')


def store(request, slug):
  filtered_store = Store.objects.filter(slug=slug).first()

  context = {
      'store': filtered_store,
  }
  return render(request, 'stores/store_profile.html', context)


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