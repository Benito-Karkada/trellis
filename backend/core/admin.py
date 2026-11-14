from django.contrib import admin
from .models import (Course, Membership, Lesson, Activity, Revision,
                     Accommodation, LTIRegistration, CanvasResourceLink)
for model in [Course, Membership, Lesson, Activity, Accommodation, LTIRegistration, CanvasResourceLink]: admin.site.register(model)
@admin.register(Revision)
class RevisionAdmin(admin.ModelAdmin):
    readonly_fields = ["activity", "number", "content", "grading", "created_by", "created_at"]
    def has_add_permission(self, request): return False
    def has_delete_permission(self, request, obj=None): return False
