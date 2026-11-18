from django.contrib import admin
from .models import Store, Product, Service, Category, BusinessType

admin.site.register(Category)
admin.site.register(BusinessType)
admin.site.register(Store)
admin.site.register(Product)
admin.site.register(Service)