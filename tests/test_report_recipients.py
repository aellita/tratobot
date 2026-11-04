from datetime import datetime, timedelta

from src.services import evening_report, morning_report


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return None


class _Session:
    def __init__(self, all_user_ids):
        self.all_user_ids = all_user_ids

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def execute(self, statement):
        if "FROM users" in str(statement):
            return _Result(list(self.all_user_ids))
        return _Result([])


class _Maker:
    def __init__(self, all_user_ids):
        self.all_user_ids = all_user_ids

    def __call__(self):
        return _Session(self.all_user_ids)


async def test_morning_without_user_ids_uses_all(monkeypatch):
    seen = []

    async def _fake_has(tg_id, session):
        seen.append(tg_id)
        return True

    monkeypatch.setattr(morning_report, "async_session_maker", _Maker([111, 222]))
    monkeypatch.setattr(morning_report, "_has_morning_report_today", _fake_has)

    await morning_report.send_morning_reports(object())

    assert seen == [111, 222]


async def test_morning_with_user_ids_only_targets_them(monkeypatch):
    seen = []

    async def _fake_has(tg_id, session):
        seen.append(tg_id)
        return True

    monkeypatch.setattr(morning_report, "async_session_maker", _Maker([111, 222]))
    monkeypatch.setattr(morning_report, "_has_morning_report_today", _fake_has)

    await morning_report.send_morning_reports(object(), user_ids=[111])

    assert seen == [111]


async def test_morning_force_skips_dedup(monkeypatch):
    seen_has = []
    seen_budget = []

    async def _fake_has(tg_id, session):
        seen_has.append(tg_id)
        return True

    async def _fake_budget(tg_id):
        seen_budget.append(tg_id)
        return None

    monkeypatch.setattr(morning_report, "async_session_maker", _Maker([111]))
    monkeypatch.setattr(morning_report, "_has_morning_report_today", _fake_has)
    monkeypatch.setattr("src.services.budget_service.get_active_budget", _fake_budget)

    await morning_report.send_morning_reports(object(), user_ids=[111], force=True)

    assert seen_has == []
    assert seen_budget == [111]


async def test_morning_force_does_not_write_log(monkeypatch):
    calls = []

    async def _fake_log(tg_id, session):
        calls.append(tg_id)

    monkeypatch.setattr(morning_report, "async_session_maker", _Maker([]))
    monkeypatch.setattr(morning_report, "_log_morning_report", _fake_log)

    await morning_report._maybe_log_morning_report(111, force=True)
    await morning_report._maybe_log_morning_report(111, force=False)

    assert calls == [111]


async def test_teaser_without_user_ids_uses_all(monkeypatch):
    seen = []

    async def _fake_budget(tg_id):
        seen.append(tg_id)
        return None

    monkeypatch.setattr(evening_report, "async_session_maker", _Maker([111, 222]))
    monkeypatch.setattr("src.services.budget_service.get_active_budget", _fake_budget)

    await evening_report.send_evening_teaser(object(), object())

    assert seen == [111, 222]


async def test_teaser_with_user_ids_only_targets_them(monkeypatch):
    seen = []

    async def _fake_budget(tg_id):
        seen.append(tg_id)
        return None

    monkeypatch.setattr(evening_report, "async_session_maker", _Maker([111, 222]))
    monkeypatch.setattr("src.services.budget_service.get_active_budget", _fake_budget)

    await evening_report.send_evening_teaser(object(), object(), user_ids=[111])

    assert seen == [111]


class _Budget:
    id = 1
    period_start_day = 1
    total_income = 1000


class _FakeBot:
    async def send_message(self, *args, **kwargs):
        return None


class _FailingBot:
    async def send_message(self, *args, **kwargs):
        raise RuntimeError("send failed")


def _patch_summary_branch(monkeypatch, *, recovery_enabled=False):
    today = morning_report.get_msk_now().date()
    period_end = datetime.combine(today - timedelta(days=1), datetime.min.time())

    class _BudgetSession(_Session):
        async def execute(self, statement):
            if "FROM budgets" in str(statement):
                return _Result([_Budget()])
            return _Result([])

    class _BudgetMaker(_Maker):
        def __call__(self):
            return _BudgetSession(self.all_user_ids)

    async def _fake_summary(*args, **kwargs):
        return object()

    async def _fake_send(*args, **kwargs):
        return None

    async def _fake_avg(*args, **kwargs):
        return 0

    async def _unexpected_budget(*args, **kwargs):
        raise AssertionError("summary branch must not fall through to daily report")

    logged = []
    expired = []

    async def _fake_log(tg_id, *, force):
        logged.append((tg_id, force))

    async def _fake_expire(budget_id):
        expired.append(budget_id)

    monkeypatch.setattr(morning_report, "async_session_maker", _BudgetMaker([111]))
    monkeypatch.setattr(morning_report, "_maybe_log_morning_report", _fake_log)
    monkeypatch.setattr(morning_report.settings, "RECOVERY_ENABLED", recovery_enabled)
    monkeypatch.setattr(
        "src.services.recovery_service.expire_active_recoveries_for_budget", _fake_expire
    )
    monkeypatch.setattr(
        "src.services.monthly_report.get_period_dates",
        lambda budget: (period_end - timedelta(days=30), period_end),
    )
    monkeypatch.setattr("src.services.monthly_report.build_summary_data", _fake_summary)
    monkeypatch.setattr("src.services.monthly_report.format_summary_text", lambda data: "text")
    monkeypatch.setattr("src.services.monthly_report.get_average_expenses", _fake_avg)
    monkeypatch.setattr("src.bot.rich_api.send_rich_message", _fake_send)
    monkeypatch.setattr("src.bot.keyboards.get_rollover_keyboard", lambda bid: object())
    monkeypatch.setattr("src.services.budget_service.get_active_budget", _unexpected_budget)

    return logged, expired


async def test_morning_force_returns_sent_ids_in_summary_branch(monkeypatch):
    logged, _ = _patch_summary_branch(monkeypatch)

    sent = await morning_report.send_morning_reports(_FakeBot(), user_ids=[111], force=True)

    assert sent == [111]
    assert logged == [(111, True)]


async def test_morning_expires_recovery_after_successful_send(monkeypatch):
    logged, expired = _patch_summary_branch(monkeypatch, recovery_enabled=True)

    sent = await morning_report.send_morning_reports(_FakeBot(), user_ids=[111], force=True)

    assert sent == [111]
    assert expired == [1]
    assert logged == [(111, True)]


async def test_morning_force_does_not_log_when_send_fails(monkeypatch):
    logged, expired = _patch_summary_branch(monkeypatch, recovery_enabled=True)

    sent = await morning_report.send_morning_reports(_FailingBot(), user_ids=[111], force=True)

    assert sent == []
    assert logged == []
    assert expired == []
