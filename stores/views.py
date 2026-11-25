from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from transactions.models import Order, OrderItem
from .models import BusinessType, Category, Store, Product, Service, Review

business_types = BusinessType.objects.all()

def stores_list(request):
  stores = Store.objects.filter(status="active").select_related("business_type").prefetch_related("categories").order_by(
      "-is_featured",
      "-rating_average",
      "name",
  )

  selected_category = request.GET.get("category", "").strip()
  if selected_category:
      stores = stores.filter(categories__slug=selected_category)

  categories = (
      Category.objects.filter(
          stores__status="active",
      )
      .distinct()
      .order_by("name")
  )

  context = {
      'stores': stores,
      'categories': categories,
      'selected_category': selected_category,
      'business_types': business_types,
  }
  return render(request, 'stores/store_list.html', context)

def all_services(request):
  services = Service.objects.filter(
      store__status="active",
      is_available=True,
  ).select_related("store", "category").order_by(
      "-is_featured",
      "-store__rating_average",
      "store__name",
      "name",
  )

  selected_category = request.GET.get("category", "").strip()
  if selected_category:
      services = services.filter(category__slug=selected_category)

  categories = (
      Category.objects.filter(
          services__store__status="active",
          services__is_available=True,
      )
      .distinct()
      .order_by("name")
  )

  context = {
      'services': services,
      'categories': categories,
      'selected_category': selected_category,
      'business_types': business_types,
  }
  return render(request, 'stores/service_list.html', context)

def all_products(request):
  products = Product.objects.filter(
      store__status="active",
      is_available=True,
  ).select_related("store", "category").order_by(
      "-is_featured",
      "-store__rating_average",
      "store__name",
      "name",
  )

  selected_category = request.GET.get("category", "").strip()
  if selected_category:
      products = products.filter(category__slug=selected_category)

  categories = (
      Category.objects.filter(
          products__store__status="active",
          products__is_available=True,
      )
      .distinct()
      .order_by("name")
  )

  context = {
      'products': products,
      'categories': categories,
      'selected_category': selected_category,
      'business_types': business_types,
  }
  return render(request, 'stores/product_list.html', context)

def store(request, slug):
  filtered_store = Store.objects.filter(slug=slug).first()
  store_reviews = Review.objects.filter(store=filtered_store)
  store_services = None
  store_products = None

  assert filtered_store is not None
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
      'business_types': business_types,
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
      'business_types': business_types,
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

def product_detail(request, slug):
  product = Product.objects.filter(slug=slug).first()
  
  context = { 
    'product': product,
    'business_types': business_types,
  }
  return render(request, 'stores/product_detail.html', context)

def service_detail(request, slug):
  service = Service.objects.filter(slug=slug).first()
  context = { 
    'service': service,
    'business_types': business_types,
    }
  return render(request, 'stores/service_detail.html', context)

def product_info(request, slug):
  product = Product.objects.filter(slug=slug).first()

  context = {
    'product':product
  }
  return render(request, 'stores/product_info.html', context )

@login_required
def submit_store_review(request, slug):
    store = get_object_or_404(Store, slug=slug)

    # Prevent store owners from reviewing their own store
    if getattr(store, "owner_id", None) == request.user.id:
        messages.warning(request, "You cannot submit a review for your own store.")
        return redirect("store:store-profile", slug=store.slug)

    # Check if this user already reviewed the store (allows updating their review)
    existing_review = Review.objects.filter(store=store, author=request.user).first()

    if request.method == "POST":
        try:
            rating = int(request.POST.get("rating", 0))
        except (ValueError, TypeError):
            rating = 0

        title = request.POST.get("title", "").strip()
        comment = request.POST.get("comment", "").strip()
        order = Order.objects.filter(customer=request.user, store=store, status="completed").first()  # Optional: link review to an order
        order_item = OrderItem.objects.filter(order=order, product__store=store).first() if order else None  # Optional: link review to an order item

        if rating < 1 or rating > 5:
            messages.error(request, "Please select a star rating between 1 and 5.")
            return render(
                request,
                "stores/review_form.html",
                {
                    "store": store,
                    "existing_review": existing_review,
                    "submitted_rating": rating,
                    "submitted_title": title,
                    "submitted_comment": comment,
                },
            )

        review_defaults = {
            "overall_rating": rating,
            "body": comment,
            "order_item": order_item,
        }
        if hasattr(Review, "title"):
            review_defaults["title"] = title

        _, created = Review.objects.update_or_create(
            store=store,
            author=request.user,
            defaults=review_defaults,
        )

        if created:
            messages.success(request, f"Thank you! Your review for {store.name} has been posted.")
        else:
            messages.success(request, f"Your review for {store.name} has been updated.")

        return redirect("store:store-profile", slug=store.slug)

    context = {
        "store": store,
        "existing_review": existing_review,
        "submitted_rating": existing_review.overall_rating if existing_review else 5,
        "submitted_title": getattr(existing_review, "title", "") if existing_review else "",
        "submitted_comment": existing_review.body if existing_review else "",
    }
    return render(request, "stores/review_form.html", context)