"""Keep native Beat run metadata separate from operator configuration writes."""

from django_celery_beat.models import PeriodicTask
from django_celery_beat.schedulers import DatabaseScheduler, ModelEntry


class RunMetadataEntry(ModelEntry):
    def save(self) -> None:
        row = PeriodicTask.objects.get(pk=self.model.pk)
        row.last_run_at = self.model.last_run_at
        row.total_run_count = self.model.total_run_count
        row.no_changes = True
        row.save(update_fields=("last_run_at", "total_run_count"))


class EditableDatabaseScheduler(DatabaseScheduler):
    """Use the public Entry extension; discovery, polling and delivery stay native."""

    Entry = RunMetadataEntry
