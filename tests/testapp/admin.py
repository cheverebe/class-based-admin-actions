from django import forms
from django.contrib import admin

from class_based_admin_actions import (
    ActionError, ClassActionsMixin, ConfirmationMixin, CsvExportAction, FormUpdateAction,
    ObjectAction, UpdateAction,
)

from .models import Article


class StatusForm(forms.Form):
    status = forms.ChoiceField(choices=[("draft", "Draft"), ("published", "Published")])


class PublishAction(UpdateAction):
    description = "Publish selected %(verbose_name_plural)s"
    update_fields = {"status": "published"}
    success_message = "Published %(count)d %(name)s."
    allowed_permissions = ("change",)


class ArchiveAction(ConfirmationMixin, PublishAction):
    update_fields = {"status": "archived"}
    success_message = "Archived %(count)d %(name)s."


class SetStatusAction(FormUpdateAction):
    form_class = StatusForm
    success_message = "Status set on %(count)d %(name)s."


class ResetViewsAction(ObjectAction):
    skip_errors = True
    log_message = "Views reset."
    success_message = "Reset %(count)d %(name)s."

    def process_object(self, obj):
        obj.title = obj.title + " (reset)"
        obj.save()
        if obj.views > 100:
            raise ActionError("too popular")
        obj.views = 0
        obj.save()


class StrictResetAction(ObjectAction):
    def process_object(self, obj):
        obj.title = "touched"
        obj.save()
        if obj.views > 100:
            raise ActionError("too popular")


class TwoAtMostAction(UpdateAction):
    update_fields = {"status": "published"}
    max_objects = 2


class ExportAction(CsvExportAction):
    fields = ["title", "status", "views"]


class AdminOnlyAction(UpdateAction):
    update_fields = {"status": "published"}
    allowed_permissions = ("publish",)


@admin.register(Article)
class ArticleAdmin(ClassActionsMixin, admin.ModelAdmin):
    actions = [
        PublishAction, ArchiveAction, SetStatusAction, ResetViewsAction, StrictResetAction,
        TwoAtMostAction, ExportAction, AdminOnlyAction,
    ]

    def has_publish_permission(self, request):
        return request.user.is_superuser
