"""The core of the plugin: ``AdminAction``, the analogue of ``django.views.generic.View``.

A Django admin action is a plain callable ``(modeladmin, request, queryset)`` with a few
attributes (``__name__``, ``short_description``, ``allowed_permissions``).
``AdminAction.as_action()`` builds such a callable from a class, exactly like
``View.as_view()`` builds a view function. A new instance is created per call, so
instance state is never shared between requests.

Behaviour is layered with cooperative mixins: every hook calls ``super()``.
"""
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.http.response import HttpResponseBase
from django.utils.text import capfirst

_SNAKE_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def camel_to_snake(name):
    return _SNAKE_RE.sub("_", name).lower()


class ActionError(Exception):
    """Raise anywhere inside an action to abort it.

    The message is shown to the user as an error and the changelist is re-displayed.
    Inside ``AtomicMixin`` the transaction is rolled back.
    """


class AdminAction:
    """Minimal action. Subclasses implement ``perform()``.

    Request lifecycle::

        as_action()() -> setup() -> dispatch()
            dispatch: has_permission() -> check_preconditions() -> handle()
            handle:   run() -> perform() -> finish() -> on_success() -> get_success_response()

    ``ActionError`` raised in any of these is reported through ``handle_error()``.
    """

    name = None
    description = None
    #: Passed to Django, which hides the action unless ``modeladmin.has_<perm>_permission``
    #: passes for at least one entry (Django's rule). Enforced again in ``has_permission()``.
    allowed_permissions = ()

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    # -- construction ---------------------------------------------------------------

    @classmethod
    def as_action(cls, **initkwargs):
        """Return a callable usable in ``ModelAdmin.actions``.

        ``initkwargs`` override class attributes, e.g.
        ``PublishAction.as_action(update_fields={"status": "live"}, name="go_live")``.
        """
        for key in initkwargs:
            if key in ("modeladmin", "request", "queryset"):
                raise TypeError(f"{cls.__name__}.as_action() received reserved argument '{key}'.")
            if not hasattr(cls, key):
                raise TypeError(
                    f"{cls.__name__}.as_action() received an invalid keyword '{key}': "
                    "it must be an attribute of the class."
                )

        def action(modeladmin, request, queryset):
            self = cls(**initkwargs)
            self.setup(modeladmin, request, queryset)
            return self.dispatch()

        meta = cls(**initkwargs)
        action.__name__ = meta.get_name()
        action.__qualname__ = f"{cls.__qualname__}.as_action.<locals>.action"
        action.__doc__ = cls.__doc__
        action.__module__ = cls.__module__
        action.short_description = meta.get_description()
        if meta.allowed_permissions:  # Django hides actions whose (even empty) tuple has no match
            action.allowed_permissions = tuple(meta.allowed_permissions)
        action.action_class = cls
        action.initkwargs = initkwargs
        return action

    def get_name(self):
        return self.name or camel_to_snake(type(self).__name__)

    def get_description(self):
        if self.description is not None:
            return self.description
        return capfirst(self.get_name().replace("_", " "))

    def setup(self, modeladmin, request, queryset):
        self.modeladmin = modeladmin
        self.request = request
        self.queryset = queryset
        self.model = modeladmin.model
        self.opts = modeladmin.opts

    # -- request lifecycle ----------------------------------------------------------

    def dispatch(self):
        try:
            if not self.has_permission():
                return self.handle_no_permission()
            self.check_preconditions()
            return self.handle()
        except ActionError as exc:
            return self.handle_error(exc)

    def has_permission(self):
        return not self.allowed_permissions or any(
            getattr(self.modeladmin, f"has_{perm}_permission")(self.request)
            for perm in self.allowed_permissions
        )

    def handle_no_permission(self):
        raise PermissionDenied

    def check_preconditions(self):
        """Hook for validations that must run before anything else (raise ``ActionError``)."""

    def get_queryset(self):
        return self.queryset

    def handle(self):
        return self.finish(self.run())

    def run(self):
        """Executes ``perform()``; wrappers such as ``AtomicMixin`` hook here."""
        return self.perform()

    def perform(self):
        raise NotImplementedError(f"{type(self).__name__} must implement perform().")

    def finish(self, result):
        if isinstance(result, HttpResponseBase):
            return result
        self.on_success(result)
        return self.get_success_response()

    def on_success(self, result):
        """Hook run after ``perform()`` returned a non-response result."""

    def get_success_url(self):
        return None

    def get_success_response(self):
        url = self.get_success_url()
        return HttpResponseRedirect(url) if url else None  # None: stay on the changelist

    def handle_error(self, exc):
        self.message_user(str(exc) or "The action could not be completed.", messages.ERROR)
        return None

    def message_user(self, message, level=messages.SUCCESS):
        self.modeladmin.message_user(self.request, message, level)
