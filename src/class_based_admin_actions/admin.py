from .base import AdminAction


class ClassActionsMixin:
    """``ModelAdmin`` mixin allowing action *classes* directly in ``actions``::

        class ArticleAdmin(ClassActionsMixin, admin.ModelAdmin):
            actions = [PublishAction, ArchiveAction.as_action(name="archive_now")]
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.actions = [
            a.as_action() if isinstance(a, type) and issubclass(a, AdminAction) else a
            for a in self.actions or ()
        ]
