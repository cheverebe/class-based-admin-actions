import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tests.testapp.models import Article


@pytest.fixture
def articles(db):
    return [Article.objects.create(title=t, views=v) for t, v in [("a", 1), ("b", 500), ("=cmd", 3)]]


@pytest.fixture
def admin_client(client, db):
    client.force_login(get_user_model().objects.create_superuser("root", "r@x.io", "pw"))
    return client


@pytest.fixture
def run(admin_client):
    """POST an action to the changelist like the admin dropdown does."""
    def _run(action, objs, **extra):
        data = {"action": action, "_selected_action": [o.pk for o in objs], **extra}
        return admin_client.post(reverse("admin:testapp_article_changelist"), data, follow=False)
    return _run
