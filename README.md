# class-based-admin-actions

Django admin actions written as classes and composed from mixins, the way class-based views are.
`AdminAction.as_action()` is to admin actions what `View.as_view()` is to views.

```python
INSTALLED_APPS = [..., "class_based_admin_actions"]   # needed for the confirmation template
```

```python
from class_based_admin_actions import (
    ClassActionsMixin, ConfirmationMixin, CsvExportAction, FormUpdateAction, UpdateAction,
)

class PublishAction(UpdateAction):
    description = "Publish selected %(verbose_name_plural)s"
    update_fields = {"status": "published"}
    success_message = "Published %(count)d %(name)s."
    allowed_permissions = ("change",)

class ArchiveAction(ConfirmationMixin, PublishAction):      # reuse + ask first
    update_fields = {"status": "archived"}

class SetStatusAction(FormUpdateAction):                    # ask for values in a form
    form_class = StatusForm

@admin.register(Article)
class ArticleAdmin(ClassActionsMixin, admin.ModelAdmin):
    actions = [PublishAction, ArchiveAction, SetStatusAction,
               CsvExportAction.as_action(fields=["title", "status"])]
```

Classes can go straight in `actions` with `ClassActionsMixin`; without it use `X.as_action(**overrides)`
(also fine for `admin.site.add_action`).

## Hierarchy

```
AdminAction                       setup / dispatch / has_permission / handle / run / perform / finish
├─ BulkAction = QuerysetMixin + SuccessMessageMixin + AtomicMixin + AdminAction
│   ├─ ObjectAction               process_object(obj), skip_errors, log_message
│   └─ UpdateAction               update_fields -> queryset.update()
│       └─ FormUpdateAction       FormMixin + UpdateAction
└─ CsvExportAction                fields, filename, CSV-injection safe
```

| Mixin | Adds |
|---|---|
| `QuerysetMixin` | `select_related`, `prefetch_related`, `max_objects` |
| `SuccessMessageMixin` | `success_message` with `%(count)d`, `%(name)s` |
| `AtomicMixin` | transaction around the run, `using` |
| `TemplateResponseMixin` | admin-context intermediate page |
| `ConfirmationMixin` | confirm page before `perform()` |
| `FormMixin` | form on the confirm page (`form_class`, `initial`, `form_valid/invalid`) |

All hooks call `super()`, so mixins combine in any order; put them before the base class.
Write your own by overriding a hook (`check_preconditions`, `get_queryset`, `run`, `on_success`, ...).
Raise `ActionError("msg")` anywhere to abort with an error message (and roll back under `AtomicMixin`).

## Notes

- Permissions: `allowed_permissions` is Django's mechanism (action hidden unless *any* listed
  `has_<perm>_permission` passes) and is re-checked on dispatch. Override `has_permission()` for more.
- `description` is `%`-formatted by Django with `verbose_name`/`verbose_name_plural`; escape literal `%` as `%%`.
- The confirmation page posts back to the changelist; the form must not define fields named
  `action`, `select_across` or `_selected_action`.
- `UpdateAction` uses `QuerySet.update()` (no `save()`, signals, or `auto_now`); use `ObjectAction` if you need them.

## Development

```
uv pip install -e . pytest pytest-django && pytest
```
