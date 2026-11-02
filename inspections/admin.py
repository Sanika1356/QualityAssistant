from django.contrib import admin

from .models import Batch, Inspection, Product

admin.site.register(Product)
admin.site.register(Batch)
admin.site.register(Inspection)
