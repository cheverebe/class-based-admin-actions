"""Ready-to-subclass actions, the analogue of ``django.views.generic``.

    AdminAction
      └─ BulkAction (QuerysetMixin, SuccessMessageMixin, AtomicMixin)
           ├─ ObjectAction        process_object(obj) for each selected object
           ├─ UpdateAction        queryset.update(**update_fields)
           │    └─ FormUpdateAction   (+ FormMixin) update with values from a form
           └─ ...
      └─ CsvExportAction (QuerysetMixin)

Add ``ConfirmationMixin`` / ``FormMixin`` in front of any of them to ask the user first.
"""
import csv

from django.contrib import messages
from django.db import transaction

from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.utils.http import content_disposition_header

from .base import ActionError, AdminAction
from .mixins import AtomicMixin, FormMixin, QuerysetMixin, SuccessMessageMixin


class BulkAction(QuerysetMixin, SuccessMessageMixin, AtomicMixin, AdminAction):
    """Batteries-included base for actions that modify the selected rows."""


class ObjectAction(BulkAction):
    """Calls ``process_object(obj)`` for every selected object.

    With ``skip_errors`` an ``ActionError`` only skips that object (its own writes are rolled
    back to a savepoint) and is reported as a warning; otherwise the whole run is aborted.
    ``log_message`` adds a ``LogEntry`` (admin history) per processed object.
    """

    skip_errors = False
    log_message = None

    def process_object(self, obj):
        raise NotImplementedError(f"{type(self).__name__} must implement process_object().")

    def perform(self):
        count, self.failures = 0, []
        for obj in self.get_queryset().iterator(chunk_size=self.iterator_chunk_size):
            label = str(obj)  # before process_object() mutates it
            try:
                if self.skip_errors:
                    with transaction.atomic(using=self.get_using()):
                        self.process_object(obj)
                else:
                    self.process_object(obj)
            except ActionError as exc:
                if not self.skip_errors:
                    raise
                self.failures.append((label, exc))
                continue
            if self.log_message:
                self.modeladmin.log_change(self.request, obj, self.log_message)
            count += 1
        return count

    def on_success(self, result):
        super().on_success(result)
        for label, exc in self.failures:
            self.message_user(f"{label}: {exc}", level=messages.WARNING)


class UpdateAction(BulkAction):
    """Sets ``update_fields`` on the selected rows with a single ``UPDATE`` query.

    Note ``QuerySet.update()`` skips ``save()``, signals and ``auto_now`` fields. Use
    ``ObjectAction`` when those matter.
    """

    update_fields = None

    def get_update_fields(self):
        if not self.update_fields:
            raise ImproperlyConfigured(f"{type(self).__name__} requires update_fields.")
        return dict(self.update_fields)

    def perform(self):
        return self.get_queryset().update(**self.get_update_fields())


class FormUpdateAction(FormMixin, UpdateAction):
    """Asks for values in a form, then updates the selection with them.

    By default every cleaned value is written; narrow it with ``update_fields`` (a list of
    form field names) or override ``get_update_fields()``.
    """

    update_fields = None

    def get_update_fields(self):
        data = self.form.cleaned_data
        return {k: data[k] for k in (self.update_fields or data)}


class CsvExportAction(QuerysetMixin, AdminAction):
    """Downloads the selection as CSV. ``fields`` may name model fields, attributes or
    methods (callables are called). String cells that start with a formula character are
    prefixed with ``'`` (``escape_formulas``) to prevent CSV injection in spreadsheets."""

    allowed_permissions = ("view",)
    fields = None
    filename = None
    header = True
    escape_formulas = True

    def get_fields(self):
        return self.fields or [f.name for f in self.opts.concrete_fields]

    def get_filename(self):
        return self.filename or f"{self.opts.model_name}.csv"

    def get_value(self, obj, field):
        value = getattr(obj, field)
        if callable(value):
            value = value()
        value = "" if value is None else value
        if self.escape_formulas and isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
            value = "'" + value
        return value

    def perform(self):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response.headers["Content-Disposition"] = content_disposition_header(True, self.get_filename())
        fields = self.get_fields()
        writer = csv.writer(response)
        if self.header:
            writer.writerow(fields)
        for obj in self.get_queryset().iterator(chunk_size=self.iterator_chunk_size):
            writer.writerow([self.get_value(obj, f) for f in fields])
        return response
