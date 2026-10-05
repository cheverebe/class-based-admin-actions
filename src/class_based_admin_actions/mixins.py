"""Reusable behaviours. Combine them with ``AdminAction`` (mixins first), like view mixins."""
from django.contrib import messages
from django.contrib.admin import helpers
from django.contrib.admin.utils import model_format_dict, model_ngettext
from django.core.exceptions import ImproperlyConfigured
from django.db import router, transaction
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

from .base import ActionError

CONFIRM_FIELD = "_cba_confirm"


class QuerysetMixin:
    """Refines the selected queryset and guards against huge selections."""

    select_related = None  # True, or a list of field names
    prefetch_related = ()
    max_objects = None
    iterator_chunk_size = 2000

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.select_related is True:
            queryset = queryset.select_related()
        elif self.select_related:
            queryset = queryset.select_related(*self.select_related)
        if self.prefetch_related:
            queryset = queryset.prefetch_related(*self.prefetch_related)
        return queryset

    def check_preconditions(self):
        super().check_preconditions()
        if self.max_objects is not None:
            count = self.queryset.count()
            if count > self.max_objects:
                raise ActionError(
                    _("This action can process at most %(max)d items at once; %(count)d were selected.")
                    % {"max": self.max_objects, "count": count}
                )


class SuccessMessageMixin:
    """Flashes ``success_message`` after a successful run.

    The message may use ``%(count)d`` and ``%(name)s`` (the singular or plural verbose name
    matching the count). ``count`` is the integer returned by ``perform()``, if any.
    """

    success_message = None

    def on_success(self, result):
        super().on_success(result)
        message = self.get_success_message(result)
        if message:
            self.message_user(message, messages.SUCCESS)

    def get_success_message(self, result):
        if not self.success_message:
            return None
        count = result if isinstance(result, int) and not isinstance(result, bool) else None
        if count is None:
            count = self.get_queryset().count()
        return self.success_message % {"count": count, "name": model_ngettext(self.opts, count)}


class AtomicMixin:
    """Runs the action in a transaction; any exception rolls everything back."""

    using = None

    def get_using(self):
        return self.using or router.db_for_write(self.model)

    def run(self):
        with transaction.atomic(using=self.get_using()):
            return super().run()


class TemplateResponseMixin:
    """Renders an intermediate admin page with the usual admin context."""

    template_name = None
    title = None
    extra_context = None
    preview_limit = 50

    def get_template_names(self):
        if self.template_name is None:
            raise ImproperlyConfigured(f"{type(self).__name__} requires template_name.")
        return [self.template_name]

    def get_title(self):
        return self.title or self.get_description() % model_format_dict(self.opts)

    def get_context_data(self, **kwargs):
        queryset = self.get_queryset()
        count = queryset.count()
        shown = list(queryset[: self.preview_limit])
        post = self.request.POST
        context = {
            **self.modeladmin.admin_site.each_context(self.request),
            "title": self.get_title(),
            "subtitle": None,
            "opts": self.opts,
            "media": self.modeladmin.media,
            "action_name": self.get_name(),
            "objects": shown,
            "object_count": count,
            "hidden_count": max(count - len(shown), 0),
            "selected_values": post.getlist(helpers.ACTION_CHECKBOX_NAME),
            "select_across": post.get("select_across", "0"),
            "action_checkbox_name": helpers.ACTION_CHECKBOX_NAME,
            "confirm_field": CONFIRM_FIELD,
            **(self.extra_context or {}),
            **kwargs,
        }
        return context

    def render_to_response(self, context):
        self.request.current_app = self.modeladmin.admin_site.name
        return TemplateResponse(self.request, self.get_template_names(), context)


class ConfirmationMixin(TemplateResponseMixin):
    """Asks for confirmation on an intermediate page before running the action.

    The page re-submits the same selection to the changelist with ``CONFIRM_FIELD`` set; the
    second request is the one that reaches ``perform()``. Subclasses hook the two phases
    through ``unconfirmed()`` and ``confirmed()``.
    """

    template_name = "class_based_admin_actions/confirmation.html"
    confirm_message = _("Are you sure you want to apply this action to the selected items?")
    confirm_button = _("Confirm")

    def is_confirmed(self):
        return CONFIRM_FIELD in self.request.POST

    def handle(self):
        if self.is_confirmed():
            return self.confirmed()
        return self.unconfirmed()

    def unconfirmed(self):
        return self.render_to_response(self.get_context_data())

    def confirmed(self):
        return super().handle()

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            confirm_message=self.confirm_message, confirm_button=self.confirm_button, **kwargs
        )


class FormMixin(ConfirmationMixin):
    """Like ``django.views.generic.edit.FormMixin``: collects input on the confirmation page.

    The validated form is available as ``self.form`` once ``perform()`` runs.
    """

    form_class = None
    initial = None
    prefix = None

    def get_form_class(self):
        if self.form_class is None:
            raise ImproperlyConfigured(f"{type(self).__name__} requires form_class.")
        return self.form_class

    def get_form_kwargs(self):
        kwargs = {"initial": dict(self.initial or {}), "prefix": self.prefix}
        if self.is_confirmed():
            kwargs.update(data=self.request.POST, files=self.request.FILES)
        return kwargs

    def get_form(self):
        return self.get_form_class()(**self.get_form_kwargs())

    def unconfirmed(self):
        self.form = self.get_form()
        return self.render_to_response(self.get_context_data())

    def confirmed(self):
        self.form = self.get_form()
        if self.form.is_valid():
            return self.form_valid(self.form)
        return self.form_invalid(self.form)

    def form_valid(self, form):
        return super().confirmed()

    def form_invalid(self, form):
        return self.render_to_response(self.get_context_data())

    def get_context_data(self, **kwargs):
        kwargs.setdefault("media", self.modeladmin.media + self.form.media)
        return super().get_context_data(form=self.form, **kwargs)
