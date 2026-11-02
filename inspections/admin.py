from django.contrib import admin

from .models import Batch, Inspection, Product, Review

admin.site.register(Product)
admin.site.register(Batch)
admin.site.register(Inspection)
admin.site.register(Review)
