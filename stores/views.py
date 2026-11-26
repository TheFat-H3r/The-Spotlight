from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render

from transactions.models import Order, OrderItem
from .models import BusinessType, Category, Store, Product, Service, Review

business_types = BusinessType.objects.all()
all_stores = Store.objects.filter(status="active")

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
      'all_stores': all_stores,
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
      'all_stores': all_stores,
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
      'all_stores': all_stores,
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
      'all_stores': all_stores,
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
      'all_stores': all_stores,
  }
  return render(request, 'stores/store_dashboard.html', context)


@login_required
def become_vendor(request):
    user_role = getattr(request.user, "role", None)

    # Reject admin accounts from applying/creating a vendor store
    if user_role == "admin":
        messages.error(request, "Admin accounts cannot create or manage seller stores.")
        return redirect("core:home")

    business_types = BusinessType.objects.all()
    categories = Category.objects.all()

    context = {
        "business_types": business_types,
      'all_stores': all_stores,
        "categories": categories,
    }

    if request.method == "POST":
        contact_email = request.POST.get("contact_email", "").strip() or request.user.email
        contact_phone = request.POST.get("contact_phone", "").strip()
        whatsapp = request.POST.get("whatsapp", "").strip()
        name = request.POST.get("name", "").strip()
        tagline = request.POST.get("tagline", "").strip()
        description = request.POST.get("description", "").strip()
        business_type_id = request.POST.get("business_type", "").strip()
        category_ids = request.POST.getlist("categories")
        pickup_location = request.POST.get("pickup_location", "").strip()
        offers_delivery = request.POST.get("offers_delivery") == "on"
        agree_terms = request.POST.get("agree_terms")
        logo = request.FILES.get("logo")
        banner = request.FILES.get("banner")

        context["form_data"] = request.POST

        if not all([contact_email, contact_phone, name, business_type_id, pickup_location, agree_terms]):
            messages.error(request, "Please fill in all required fields and accept the terms and conditions.")
            return render(request, "core/become-vendor.html", context)

        # Enforce unique_store_name_per_owner constraint cleanly
        if Store.objects.filter(owner=request.user, name__iexact=name).exists():
            messages.error(request, f"You already have a store named '{name}'. Please choose another name.")
            return render(request, "core/become-vendor.html", context)

        # Validate BusinessType
        business_type = BusinessType.objects.filter(pk=business_type_id).first()
        if not business_type:
            messages.error(request, "Please select a valid business type.")
            return render(request, "core/become-vendor.html", context)

        # Validate file size (max 5MB)
        max_size = 5 * 1024 * 1024
        if (logo and logo.size > max_size) or (banner and banner.size > max_size):
            messages.error(request, "Logo and cover images must be 5MB or smaller.")
            return render(request, "core/become-vendor.html", context)

        try:
            with transaction.atomic():
                store = Store(
                    name=name,
                    tagline=tagline,
                    description=description,
                    business_type=business_type,
                    contact_email=contact_email,
                    contact_phone=contact_phone,
                    whatsapp=whatsapp,
                    pickup_location=pickup_location,
                    offers_delivery=offers_delivery,
                    logo=logo,
                    banner=banner,
                    status=Store.Status.DRAFT,
                )
                store.owner = request.user
                store.save()

                if category_ids:
                    valid_categories = Category.objects.filter(pk__in=category_ids)
                    store.categories.set(valid_categories)

                # Promote customer role to vendor
                if request.user.role == "customer":
                    request.user.role = "vendor"
                    request.user.save(update_fields=["role"])

        except IntegrityError:
            messages.error(request, "Could not create your store due to a duplicate name. Please try again.")
            return render(request, "core/become-vendor.html", context)

        messages.success(
            request,
            f"Your store '{store.name}' has been created as a draft and submitted for review!",
        )
        return redirect("shopkeeper:home") 

    return render(request, "stores/store_form.html", context)

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
    product = get_object_or_404(
        Product.objects.select_related("store", "category"),
        slug=slug,
        is_available=True,
    )

    related_products = (
        Product.objects.filter(category=product.category, is_available=True)
        .exclude(pk=product.pk)
        .select_related("store", "category")[:4]
        if product.category
        else Product.objects.none()
    )

    reviews = Review.objects.filter(order_item__product=product).select_related("author").order_by("-created_at")

    context = {
        "product": product,
        "related_products": related_products,
        "reviews": reviews,
        "business_types": BusinessType.objects.all(),
        "all_stores": Store.objects.filter(status="active"),
    }
    return render(request, "stores/product_detail.html", context)

def service_detail(request, slug):
  service = Service.objects.filter(slug=slug).first()
  context = { 
    'service': service,
    'business_types': business_types,
    'all_stores': all_stores,
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