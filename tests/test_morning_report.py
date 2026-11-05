from src.db.models.models import DailyReportsLog
from src.services import morning_report
from src.utils.helpers import get_msk_now


class _FakeSession:
    def __init__(self, added, commits):
        self.added = added
        self.commits = commits

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits.append(True)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return None


class _QuerySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, statement):
        if "FROM users" in str(statement):
            return _Result([111])
        return _Result([])


async def test_log_morning_report_writes_one_row(monkeypatch):
    added = []
    commits = []

    monkeypatch.setattr(
        morning_report,
        "async_session_maker",
        lambda: _FakeSession(added, commits),
    )

    await morning_report._log_morning_report(111)

    assert len(added) == 1
    row = added[0]
    assert isinstance(row, DailyReportsLog)
    assert row.telegram_id == 111
    assert row.report_type == "morning"
    assert row.sent_date == get_msk_now().date()
    assert commits == [True]


async def test_morning_skips_user_with_report_today(monkeypatch):
    seen = []
    logged = []

    async def _fake_has(tg_id, session):
        seen.append(tg_id)
        return True

    async def _fake_log(tg_id):
        logged.append(tg_id)

    async def _unexpected_budget(*args, **kwargs):
        raise AssertionError("dedup skip must happen before budget lookup")

    monkeypatch.setattr(morning_report, "async_session_maker", lambda: _QuerySession())
    monkeypatch.setattr(morning_report, "_has_morning_report_today", _fake_has)
    monkeypatch.setattr(morning_report, "_log_morning_report", _fake_log)
    monkeypatch.setattr("src.services.budget_service.get_active_budget", _unexpected_budget)

    await morning_report.send_morning_reports(object())

    assert seen == [111]
    assert logged == []
