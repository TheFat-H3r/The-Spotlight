from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from stores.models import Store
from .models import Advertisement, Announcement


# ==========================================
# 1. ADVERTISEMENT VIEWS
# ==========================================

def advertisement_list(request):

  ads = Advertisement.objects.filter(status=Advertisement.Status.ACTIVE).order_by('-created_at')
  context = {'ads': ads}
  return render(request, 'marketing/ad_list.html', context)


def advertisement_detail(request, slug):
  ad = get_object_or_404(Advertisement, slug=slug)
  
  # Increment impressions view counter
  ad.impressions_count += 1
  ad.save(update_fields=['impressions_count'])

  context = {'ad': ad}
  return render(request, 'marketing/ad_detail.html', context)


@login_required
def advertisement_create(request):
  # Get stores owned by the user so they can optionally link the ad to their store
  user_stores = Store.objects.filter(vendor__user=request.user)

  if request.method == 'POST':
    title = request.POST.get('title')
    description = request.POST.get('description')
    target_url = request.POST.get('target_url')
    start_date = request.POST.get('start_date')
    end_date = request.POST.get('end_date')
    budget = request.POST.get('budget', 0.00)
    store_id = request.POST.get('store_id')  # Optional store selection
    banner_image = request.FILES.get('banner_image')

    store = user_stores.filter(id=store_id).first() if store_id else None

    Advertisement.objects.create(
        user=request.user,
        store=store,
        title=title,
        description=description,
        target_url=target_url,
        start_date=start_date,
        end_date=end_date,
        budget=budget,
        banner_image=banner_image,
        status=Advertisement.Status.PENDING # Default to pending approval
    )
    return redirect('advertisement-list')

  context = {'user_stores': user_stores}
  return render(request, 'marketing/ad_form.html', context)


@login_required
def advertisement_update(request, slug):
  ad = get_object_or_404(Advertisement, slug=slug, user=request.user)
  user_stores = Store.objects.filter(vendor__user=request.user)

  if request.method == 'POST':
    ad.title = request.POST.get('title', ad.title)
    ad.description = request.POST.get('description', ad.description)
    ad.target_url = request.POST.get('target_url', ad.target_url)
    
    store_id = request.POST.get('store_id')
    ad.store = user_stores.filter(id=store_id).first() if store_id else None

    if 'banner_image' in request.FILES:
      ad.banner_image = request.FILES['banner_image']

    ad.save()
    return redirect('advertisement-detail', slug=ad.slug)

  context = {'ad': ad, 'user_stores': user_stores}
  return render(request, 'marketing/ad_form.html', context)


@login_required
def advertisement_delete(request, slug):
  ad = get_object_or_404(Advertisement, slug=slug, user=request.user)
  if request.method == 'POST':
    ad.delete()
    return redirect('advertisement-list')

  context = {'ad': ad}
  return render(request, 'marketing/ad_confirm_delete.html', context)


# ==========================================
# 2. ANNOUNCEMENT VIEWS
# ==========================================

def announcement_list(request):
  
  announcements = Announcement.objects.filter(is_active=True).order_by('-created_at')
  context = {'announcements': announcements}
  return render(request, 'marketing/announcement_list.html', context)


def announcement_detail(request, slug):
  
  announcement = get_object_or_404(Announcement, slug=slug, is_active=True)
  context = {'announcement': announcement}
  return render(request, 'marketing/announcement_detail.html', context)


@login_required
def announcement_create(request):
  
  user_stores = Store.objects.filter(vendor__user=request.user)

  if request.method == 'POST':
    title = request.POST.get('title')
    content = request.POST.get('content')
    start_date = request.POST.get('start_date') or None
    end_date = request.POST.get('end_date') or None
    store_id = request.POST.get('store_id')
    banner_image = request.FILES.get('banner_image')

    store = user_stores.filter(id=store_id).first() if store_id else None

    Announcement.objects.create(
        user=request.user,
        store=store,
        title=title,
        content=content,
        start_date=start_date,
        end_date=end_date,
        banner_image=banner_image,
        is_active=True
    )
    return redirect('announcement-list')

  context = {'user_stores': user_stores}
  return render(request, 'marketing/announcement_form.html', context)


@login_required
def announcement_update(request, slug):
  
  announcement = get_object_or_404(Announcement, slug=slug, user=request.user)
  user_stores = Store.objects.filter(vendor__user=request.user)

  if request.method == 'POST':
    announcement.title = request.POST.get('title', announcement.title)
    announcement.content = request.POST.get('content', announcement.content)
    
    store_id = request.POST.get('store_id')
    announcement.store = user_stores.filter(id=store_id).first() if store_id else None

    if 'banner_image' in request.FILES:
      announcement.banner_image = request.FILES['banner_image']

    announcement.save()
    return redirect('announcement-detail', slug=announcement.slug)

  context = {'announcement': announcement, 'user_stores': user_stores}
  return render(request, 'marketing/announcement_form.html', context)


@login_required
def announcement_delete(request, slug):
  
  announcement = get_object_or_404(Announcement, slug=slug, user=request.user)
  if request.method == 'POST':
    announcement.delete()
    return redirect('announcement-list')

  context = {'announcement': announcement}
  return render(request, 'marketing/announcement_confirm_delete.html', context)