from django.shortcuts import render

def home(request):
    return render(request, 'core/home.html')

def about_us(request):
    return render(request, 'core/about.html')

def contact_us(request):
    return render(request, 'core/contact.html')