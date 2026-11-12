from django.contrib import admin
from .models import UserProfile, PBRMapper


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("PBR", "user", "birth_date")
    search_fields = ("PBR", "user__first_name", "user__last_name")

@admin.register(PBRMapper)
class PBRMapperAdmin(admin.ModelAdmin):
    list_display = ("PBR", "employee_name")
    search_fields = ("PBR", "employee_name")