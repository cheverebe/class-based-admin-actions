from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=100)
    status = models.CharField(max_length=20, default="draft")
    views = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.title
