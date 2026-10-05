import csv
import io

import pytest
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.urls import reverse

from class_based_admin_actions import AdminAction, UpdateAction
from class_based_admin_actions.mixins import CONFIRM_FIELD
from tests.testapp.admin import ArticleAdmin, PublishAction
from tests.testapp.models import Article


def messages_of(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


def statuses():
    return {a.title: a.status for a in Article.objects.all()}


# -- construction -------------------------------------------------------------------


def test_as_action_metadata():
    action = PublishAction.as_action(name="go_live")
    assert action.__name__ == "go_live"
    assert action.short_description == "Publish selected %(verbose_name_plural)s"
    assert action.allowed_permissions == ("change",)
    assert not hasattr(AdminAction.as_action(), "allowed_permissions")
    assert action.action_class is PublishAction


def test_default_name_and_description():
    class CSVExportAllAction(AdminAction):
        pass

    action = CSVExportAllAction.as_action()
    assert action.__name__ == "csv_export_all_action"
    assert action.short_description == "Csv export all action"


def test_as_action_rejects_unknown_and_reserved_kwargs():
    with pytest.raises(TypeError, match="invalid keyword"):
        PublishAction.as_action(nope=1)
    with pytest.raises(TypeError, match="reserved"):
        PublishAction.as_action(request=1)


def test_initkwargs_override_class_attributes(articles, run):
    class Custom(PublishAction):
        pass

    assert Custom.as_action(update_fields={"status": "x"}).initkwargs == {"update_fields": {"status": "x"}}
    assert Custom.update_fields == {"status": "published"}


def test_class_in_actions_is_converted():
    from django.contrib import admin
    names = [getattr(a, "__name__", a) for a in ArticleAdmin(Article, admin.site).actions]
    assert "publish_action" in names and "archive_action" in names


def test_lazy_description_formatted_by_django(admin_client, articles):
    html = admin_client.get(reverse("admin:testapp_article_changelist")).content.decode()
    assert "Publish selected articles" in html


# -- update / messages --------------------------------------------------------------


def test_update_action_updates_only_selection_and_flashes(articles, run):
    response = run("publish_action", articles[:2])
    assert response.status_code == 302
    assert statuses() == {"a": "published", "b": "published", "=cmd": "draft"}
    assert messages_of(response) == ["Published 2 articles."]


def test_singular_name(articles, run):
    assert messages_of(run("publish_action", articles[:1])) == ["Published 1 article."]


# -- object action ------------------------------------------------------------------


def test_object_action_skip_errors_rolls_back_failed_object_only(articles, run):
    response = run("reset_views_action", articles)
    titles = {a.title: a.views for a in Article.objects.all()}
    assert titles == {"a (reset)": 0, "b": 500, "=cmd (reset)": 0}  # 'b' fully rolled back
    msgs = messages_of(response)
    assert "Reset 2 articles." in msgs and "b: too popular" in msgs
    assert LogEntry.objects.count() == 2


def test_object_action_without_skip_errors_aborts_everything(articles, run):
    response = run("strict_reset_action", articles)
    assert all(a.title != "touched" for a in Article.objects.all())  # whole run rolled back
    assert messages_of(response) == ["too popular"]


# -- confirmation & forms -----------------------------------------------------------


def test_confirmation_page_then_perform(articles, run):
    response = run("archive_action", articles[:1], select_across="0")
    assert response.status_code == 200
    body = response.content.decode()
    assert CONFIRM_FIELD in body and 'name="action" value="archive_action"' in body
    assert statuses()["a"] == "draft"  # nothing happened yet

    response = run("archive_action", articles[:1], **{CONFIRM_FIELD: "1"})
    assert response.status_code == 302
    assert statuses()["a"] == "archived"
    assert messages_of(response) == ["Archived 1 article."]


def test_confirmation_preserves_select_across(articles, run):
    body = run("archive_action", articles[:1], select_across="1").content.decode()
    assert 'name="select_across" value="1"' in body


def test_form_flow_invalid_then_valid(articles, run):
    first = run("set_status_action", articles[:2])
    assert first.status_code == 200 and "<select" in first.content.decode()

    invalid = run("set_status_action", articles[:2], **{CONFIRM_FIELD: "1", "status": "bogus"})
    assert invalid.status_code == 200
    assert "Select a valid choice" in invalid.content.decode()
    assert set(statuses().values()) == {"draft"}

    valid = run("set_status_action", articles[:2], **{CONFIRM_FIELD: "1", "status": "published"})
    assert valid.status_code == 302
    assert statuses() == {"a": "published", "b": "published", "=cmd": "draft"}
    assert messages_of(valid) == ["Status set on 2 articles."]


# -- preconditions, permissions -----------------------------------------------------


def test_max_objects(articles, run):
    response = run("two_at_most_action", articles)
    assert "at most 2 items" in messages_of(response)[0]
    assert set(statuses().values()) == {"draft"}
    run("two_at_most_action", articles[:2])
    assert list(statuses().values()).count("published") == 2


def test_action_hidden_and_denied_without_permission(articles, client):
    user = get_user_model().objects.create_user("staff", password="pw", is_staff=True)
    from django.contrib.auth.models import Permission
    user.user_permissions.add(*Permission.objects.filter(codename__in=["view_article", "change_article"]))
    client.force_login(user)
    url = reverse("admin:testapp_article_changelist")
    html = client.get(url).content.decode()
    assert "Admin only action" not in html and "Publish selected" in html
    client.post(url, {"action": "admin_only_action", "_selected_action": [articles[0].pk]})
    assert set(statuses().values()) == {"draft"}


def test_has_permission_enforced_even_if_action_is_called_directly(articles, rf):
    from django.core.exceptions import PermissionDenied
    from django.contrib import admin

    request = rf.post("/")
    request.user = get_user_model().objects.create_user("nobody", password="pw")
    action = UpdateAction.as_action(update_fields={"status": "x"}, allowed_permissions=("change",))
    with pytest.raises(PermissionDenied):
        action(ArticleAdmin(Article, admin.site), request, Article.objects.all())


# -- export -------------------------------------------------------------------------


def test_csv_export_escapes_formulas(articles, run):
    response = run("export_action", articles)
    assert response["Content-Type"].startswith("text/csv")
    assert 'filename="article.csv"' in response["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.content.decode())))
    assert rows[0] == ["title", "status", "views"]
    assert ["'=cmd", "draft", "3"] in rows and ["a", "draft", "1"] in rows
