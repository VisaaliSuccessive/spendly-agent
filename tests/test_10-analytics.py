"""
Tests for Step 10: Analytics feature
Spec: .claude/specs/10-analytics.md

PR 1 — DB layer only:
- Unit: get_monthly_trend() returns the last N calendar months, oldest -> newest,
  with correct totals and percent scaled to the max month
- Unit: get_monthly_trend() fills in zero-expense months with total 0.00 / percent 0
- Unit: get_spending_insights() returns correct average and highest expense
- Unit: get_spending_insights() returns None/None when the user has no expenses
- Unit: get_spending_insights() respects an optional date range
"""

from datetime import date, datetime, timedelta

import pytest
from werkzeug.security import generate_password_hash

import database.db as db_module
from app import app as flask_app
from database.db import init_db
from database.queries import (
    get_category_breakdown,
    get_monthly_trend,
    get_spending_insights,
    get_total_for_range,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_spendly.db")


@pytest.fixture
def app(db_path, monkeypatch):
    monkeypatch.setattr(db_module, "DB_PATH", db_path)

    flask_app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "WTF_CSRF_ENABLED": False,
        }
    )

    with flask_app.app_context():
        init_db()
        yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def registered_user(client):
    email = "testuser@example.com"
    password = "testpass123"
    client.post(
        "/register",
        data={
            "name": "Test User",
            "email": email,
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=True,
    )
    conn = db_module.get_db()
    row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row["id"], email, password


@pytest.fixture
def auth_client(client, registered_user):
    user_id, _email, _password = registered_user
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["user_name"] = "Test User"
    return client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_user(name, email):
    conn = db_module.get_db()
    cursor = conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (name, email, generate_password_hash("pass")),
    )
    conn.commit()
    user_id = cursor.lastrowid
    conn.close()
    return user_id


def _create_expense(
    user_id, amount=50.0, category="Food", date="2026-03-20", description="Lunch"
):
    conn = db_module.get_db()
    cursor = conn.execute(
        "INSERT INTO expenses (user_id, amount, category, date, description) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, amount, category, date, description),
    )
    conn.commit()
    expense_id = cursor.lastrowid
    conn.close()
    return expense_id


# ===========================================================================
# Unit tests for get_monthly_trend()
# ===========================================================================


class TestGetMonthlyTrend:
    def test_returns_requested_number_of_months(self, app):
        user_id = _create_user("Owner", "owner@example.com")

        result = get_monthly_trend(user_id, months=6)

        assert len(result) == 6

    def test_months_ordered_oldest_to_newest(self, app):
        user_id = _create_user("Owner", "owner@example.com")

        result = get_monthly_trend(user_id, months=3)
        labels = [entry["label"] for entry in result]

        assert labels == sorted(
            labels, key=lambda label: datetime.strptime(label, "%b %Y")
        )

    def test_zero_expense_months_have_zero_total_and_percent(self, app):
        user_id = _create_user("Owner", "owner@example.com")

        result = get_monthly_trend(user_id, months=6)

        for entry in result:
            assert entry["total"] == "0.00"
            assert entry["percent"] == 0

    def test_current_month_total_reflects_seeded_expense(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        today = date.today().isoformat()
        _create_expense(user_id, amount=150.0, date=today)

        result = get_monthly_trend(user_id, months=6)

        assert result[-1]["total"] == "150.00"
        assert result[-1]["percent"] == 100

    def test_percent_scaled_to_max_month(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        today = date.today().isoformat()
        _create_expense(user_id, amount=100.0, date=today)
        _create_expense(user_id, amount=100.0, date=today)

        result = get_monthly_trend(user_id, months=6)

        assert result[-1]["total"] == "200.00"
        assert result[-1]["percent"] == 100

    def test_ignores_expenses_belonging_to_other_users(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        other_id = _create_user("Other", "other@example.com")
        today = date.today().isoformat()
        _create_expense(other_id, amount=999.0, date=today)

        result = get_monthly_trend(user_id, months=6)

        assert result[-1]["total"] == "0.00"


# ===========================================================================
# Unit tests for get_spending_insights()
# ===========================================================================


class TestGetSpendingInsights:
    def test_no_expenses_returns_none_average_and_highest(self, app):
        user_id = _create_user("Owner", "owner@example.com")

        result = get_spending_insights(user_id)

        assert result["average"] is None
        assert result["highest"] is None

    def test_average_computed_correctly(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        _create_expense(user_id, amount=100.0)
        _create_expense(user_id, amount=200.0)

        result = get_spending_insights(user_id)

        assert result["average"] == "150.00"

    def test_highest_expense_identified_correctly(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        _create_expense(user_id, amount=100.0, category="Food")
        _create_expense(user_id, amount=500.0, category="Bills", date="2026-04-03")

        result = get_spending_insights(user_id)

        assert result["highest"]["amount"] == "500.00"
        assert result["highest"]["category"] == "Bills"

    def test_ignores_expenses_belonging_to_other_users(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        other_id = _create_user("Other", "other@example.com")
        _create_expense(other_id, amount=999.0)

        result = get_spending_insights(user_id)

        assert result["average"] is None
        assert result["highest"] is None

    def test_respects_date_range_filter(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        _create_expense(user_id, amount=100.0, date="2026-01-15")
        _create_expense(user_id, amount=900.0, date="2026-04-15")

        result = get_spending_insights(
            user_id, date_from="2026-01-01", date_to="2026-01-31"
        )

        assert result["average"] == "100.00"
        assert result["highest"]["amount"] == "100.00"


# ===========================================================================
# Unit tests for get_total_for_range()
# ===========================================================================


class TestGetTotalForRange:
    def test_no_expenses_returns_zero(self, app):
        user_id = _create_user("Owner", "owner@example.com")

        assert get_total_for_range(user_id) == 0

    def test_sums_only_matching_date_range(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        _create_expense(user_id, amount=100.0, date="2026-01-15")
        _create_expense(user_id, amount=900.0, date="2026-04-15")

        assert get_total_for_range(user_id, "2026-01-01", "2026-01-31") == 100.0

    def test_ignores_expenses_belonging_to_other_users(self, app):
        user_id = _create_user("Owner", "owner@example.com")
        other_id = _create_user("Other", "other@example.com")
        _create_expense(other_id, amount=500.0)

        assert get_total_for_range(user_id) == 0


# ===========================================================================
# Route: GET /analytics — trend chart (PR 2)
# ===========================================================================


class TestAnalyticsTrendChart:
    def test_unauthenticated_redirects_to_login(self, client, app):
        response = client.get("/analytics")

        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_authenticated_returns_200(self, auth_client):
        response = auth_client.get("/analytics")

        assert response.status_code == 200

    def test_renders_six_trend_bars(self, auth_client):
        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert body.count("trend-bar-col") == 6

    def test_current_month_expense_reflected_in_chart(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        today = date.today().isoformat()
        _create_expense(user_id, amount=250.0, date=today)

        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert "250.00" in body

    def test_no_longer_shows_coming_soon_placeholder(self, auth_client):
        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert "Coming Soon" not in body


# ===========================================================================
# Route: GET /analytics — category breakdown (PR 3)
# ===========================================================================


class TestAnalyticsCategoryBreakdown:
    def test_category_breakdown_matches_profile_page(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        _create_expense(user_id, amount=100.0, category="Food")
        _create_expense(user_id, amount=300.0, category="Bills")

        analytics_body = auth_client.get("/analytics").data.decode()
        profile_body = auth_client.get("/profile").data.decode()

        expected = get_category_breakdown(user_id)
        for cat in expected:
            assert f"₹{cat['amount']}" in analytics_body
            assert f"₹{cat['amount']}" in profile_body

    def test_empty_state_shown_when_no_expenses(self, auth_client):
        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert "No expenses yet." in body

    def test_category_rows_rendered_for_seeded_expenses(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        _create_expense(user_id, amount=50.0, category="Transport")

        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert "Transport" in body
        assert "cat-bar--transport" in body


# ===========================================================================
# Route: GET /analytics — insight stat tiles (PR 4)
# ===========================================================================


class TestAnalyticsInsightTiles:
    def test_average_and_highest_tiles_render_correct_values(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        today = date.today().isoformat()
        _create_expense(user_id, amount=100.0, category="Food", date=today)
        _create_expense(user_id, amount=300.0, category="Bills", date=today)

        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert "200.00" in body  # average
        assert "300.00" in body  # highest

    def test_no_expenses_shows_dash_for_tiles(self, auth_client):
        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert body.count("—") >= 3

    def test_month_over_month_shows_dash_when_previous_month_empty(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        today = date.today().isoformat()
        _create_expense(user_id, amount=100.0, date=today)

        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert "stat-tile-increase" not in body
        assert "stat-tile-decrease" not in body

    def test_month_over_month_percent_increase_rendered(
        self, auth_client, registered_user
    ):
        user_id, _email, _password = registered_user
        today = date.today()
        prev_month_last_day = today.replace(day=1) - timedelta(days=1)

        _create_expense(user_id, amount=100.0, date=prev_month_last_day.isoformat())
        _create_expense(user_id, amount=200.0, date=today.isoformat())

        response = auth_client.get("/analytics")
        body = response.data.decode()

        assert "stat-tile-increase" in body
        assert "+100%" in body
