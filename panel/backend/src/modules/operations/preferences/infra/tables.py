from papilio.infra.db.table import BaseTable

from src.modules.operations.preferences.domain.models import (
    PreferencesRevisionModel,
)


class PreferencesRevisionTable(
    PreferencesRevisionModel, BaseTable, table=True
):
    pass
