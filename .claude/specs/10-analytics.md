# Spec: Analytics

## Overview
The `/analytics` route currently renders a static "Coming Soon" placeholder card. This step replaces that placeholder with real spending insights built from the user's existing expense data: a monthly spending trend, a category breakdown, and a row of quick-insight stat tiles (average per transaction, highest single expense, month-over-month change). It reuses the same expense data already surfaced on the profile page — no new tables, no new user input, no external charting library.

## Depends on
- 01-database-setup (expenses table)
- 07-add-expense (real expense rows to visualize)
- 05-backend-routes-for-profile-page (established `_build_date_filter` pattern and `get_category_breakdown` query this step reuses)

## Routes
No new routes. Modify the existing route:
- `GET /analytics` — logged-in only (already redirects to `login` when `session.user_id` is absent) — now queries and passes real analytics data instead of rendering a static template with no context.

## Database changes
No new tables or columns. Add two new read-only functions to `database/queries.py`, following the existing `_build_date_filter` pattern:

- `get_monthly_trend(user_id, months=6)` — total spend per calendar month for the last `months` months (including the current month), oldest → newest. Returns a list of `{label, total, percent}` where `percent` is each month's total scaled against the highest month in the window (for CSS bar heights).
- `get_spending_insights(user_id, date_from=None, date_to=None)` — returns `{average, highest}` where `average` is total ÷ count for the given range (or `None` if count is 0), and `highest` is the single largest expense in range (`{amount, category, date}` or `None` if there are no expenses).

## Templates
- **Modify:** `templates/analytics.html` — remove the "Coming Soon" card; add monthly trend bar chart, category breakdown list (same percent-bar pattern as `templates/profile.html`), and three stat tiles (average per transaction, highest expense, month-over-month % change). Extends `base.html` as before.
- **Create:** none.

## Files to change
- `app.py` — `analytics()` route: query monthly trend, category breakdown, insights, and current vs. previous calendar month totals; pass to template.
- `database/queries.py` — add `get_monthly_trend` and `get_spending_insights`.
- `templates/analytics.html` — replace placeholder content with real markup.
- `static/css/analytics.css` — replace "coming soon" styles with chart bar, stat tile, and breakdown styles.

## Files to create
No new files.

## New dependencies
No new dependencies.

## Rules for implementation
- No SQLAlchemy or ORMs
- Parameterised queries only (`?` placeholders)
- Passwords hashed with werkzeug (n/a to this step, no auth changes)
- Use CSS variables — never hardcode new hex values in `static/css/analytics.css`; reuse `var(--accent)` and friends already defined in `static/css/style.css`
- All templates extend `base.html`
- Chart bars are pure CSS (server computes `percent`, template sets bar height/width inline via that value) — no JS charting library, no new npm/pip packages
- Guard every division (`average`, month-over-month %) against zero-expense / zero-count cases

## Definition of done
- [ ] Visiting `/analytics` while logged out redirects to `/login`
- [ ] Visiting `/analytics` while logged in as `demo@spendly.com` shows a monthly trend bar per month with expense data, most recent 6 months
- [ ] Category breakdown on `/analytics` matches the percentages shown on `/profile` for the same data
- [ ] Average-per-transaction tile shows the correct value for the demo user's seeded expenses
- [ ] Highest-expense tile shows the correct single largest seeded expense
- [ ] Month-over-month tile shows a correct percent change (or a neutral "—" when the previous month has zero expenses)
- [ ] A newly registered user with zero expenses sees an empty-state message on `/analytics` instead of a NaN, divide-by-zero error, or blank chart
- [ ] No hardcoded hex colors introduced in `static/css/analytics.css`
