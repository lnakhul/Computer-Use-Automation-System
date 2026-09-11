"""Small local web surface used for adapter and future end-to-end tests."""

from __future__ import annotations

import time
from dataclasses import dataclass

from flask import Flask, redirect, render_template_string, request, url_for


@dataclass(frozen=True)
class MemberRecord:
    member_id: str
    full_name: str
    savings_balance: str


MEMBER_RECORDS = {
    "12345": MemberRecord("12345", "Alex Morgan", "$1,240.50"),
    "67890": MemberRecord("67890", "Jordan Lee", "$85.00"),
}

BASE_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ page_title }}</title>
  <style>
    body { background: #eef1f3; color: #20262b; font-family: Georgia, serif; margin: 0; }
    header { background: #17324d; color: white; padding: 18px 28px; }
    main { background: white; border: 1px solid #b5bdc4; margin: 28px auto; max-width: 850px; padding: 24px 30px; }
    label { display: block; font-weight: bold; margin-top: 14px; }
    input, select { border: 1px solid #687681; font: inherit; margin-top: 5px; padding: 8px; width: 280px; }
    button { background: #174e76; border: 1px solid #0b304a; color: white; cursor: pointer; font: inherit; margin-top: 18px; padding: 9px 16px; }
    table { border-collapse: collapse; margin-top: 18px; width: 100%; }
    th, td { border: 1px solid #89949c; padding: 10px; text-align: left; }
    th { background: #dce3e8; width: 35%; }
    .error { background: #fff0f0; border: 1px solid #b33131; color: #7c1515; margin: 14px 0; padding: 10px; }
    .notice { background: #f4f0dc; border: 1px solid #a58d39; margin: 14px 0; padding: 10px; }
    .dialog { background: #fff7d6; border: 2px solid #9b7f1b; padding: 16px; }
    a { color: #174e76; }
  </style>
</head>
<body>
  <header><strong>Member Servicing Console</strong> | Branch Operations</header>
  <main>{{ content|safe }}</main>
</body>
</html>
"""


SEARCH_CONTENT = """
<h1>Member Search</h1>
<p>Use the member servicing index to locate an account record.</p>
{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
{% if notice %}<div class="notice">{{ notice }}</div>{% endif %}
<form method="post" action="{{ url_for('search_member') }}">
  <label for="member-id">Member ID</label>
  <input id="member-id" name="member_id" type="text" value="{{ member_id }}" maxlength="5">
  <button type="submit">Search</button>
</form>
"""


def create_demo_application() -> Flask:
    application = Flask(__name__)

    @application.get("/")
    def home() -> str:
        return redirect(url_for("member_search"))

    @application.get("/members/search")
    def member_search() -> str:
        notice = None
        if request.args.get("simulate") == "delay":
            time.sleep(0.2)
            notice = "The member index responded after a short delay."
        return _render_page("Member Search", SEARCH_CONTENT, error=None, member_id="", notice=notice)

    @application.post("/members/search")
    def search_member() -> str:
        member_id = request.form.get("member_id", "").strip()
        if not member_id:
            return _render_page(
                "Member Search",
                SEARCH_CONTENT,
                error="Member ID is required.",
                member_id=member_id,
                notice=None,
            ), 400
        if not member_id.isdigit() or len(member_id) != 5:
            return _render_page(
                "Member Search",
                SEARCH_CONTENT,
                error="Member ID must contain exactly five digits.",
                member_id=member_id,
                notice=None,
            ), 400
        if member_id not in MEMBER_RECORDS:
            return redirect(url_for("member_not_found", member_id=member_id))
        return redirect(url_for("member_detail", member_id=member_id))

    @application.get("/members/not-found/<member_id>")
    def member_not_found(member_id: str) -> str:
        return _render_page(
            "Member Not Found",
            '<h1>Member Search Result</h1><div class="error" role="alert">Member not found</div><p>No member record matches the requested identifier.</p><a href="/members/search">Return to search</a>',
            error=None,
            member_id=member_id,
            notice=None,
        )

    @application.get("/members/<member_id>")
    def member_detail(member_id: str) -> str:
        member = MEMBER_RECORDS.get(member_id)
        if member is None:
            return redirect(url_for("member_not_found", member_id=member_id))
        detail_content = """
<h1>Member Details</h1>
<table>
  <tr><th>Member ID</th><td>{{ member.member_id }}</td></tr>
  <tr><th>Member Name</th><td>{{ member.full_name }}</td></tr>
    <tr><th>Savings balance</th><td aria-label="Savings balance">{{ member.savings_balance }}</td></tr>
</table>
<p><a href="{{ url_for('sub_account_form', member_id=member.member_id) }}">Open new sub-account</a></p>
"""
        if request.args.get("simulate") == "dialog":
            detail_content += """
<div class="dialog" role="dialog" aria-label="Session notice">
  <strong>Session notice</strong><p>A servicing notice requires acknowledgement.</p>
  <a href="{{ url_for('member_detail', member_id=member.member_id) }}">Dismiss notice</a>
</div>
"""
        return _render_page("Member Details", detail_content, member=member)

    @application.get("/members/<member_id>/sub-account")
    def sub_account_form(member_id: str) -> str:
        member = MEMBER_RECORDS.get(member_id)
        if member is None:
            return redirect(url_for("member_not_found", member_id=member_id))
        form_content = """
<h1>New Sub-Account Request</h1>
<p>Member: {{ member.full_name }} ({{ member.member_id }})</p>
{% if error %}<div class="error" role="alert">{{ error }}</div>{% endif %}
<form method="post" action="{{ url_for('sub_account_review', member_id=member.member_id) }}">
  <label for="account-type">Account type</label>
  <select id="account-type" name="account_type">
    <option value="holiday">Holiday savings</option>
    <option value="emergency">Emergency savings</option>
  </select>
  <label for="opening-amount">Opening amount</label>
  <input id="opening-amount" name="opening_amount" type="text">
  <button type="submit">Review request</button>
</form>
"""
        return _render_page("New Sub-Account Request", form_content, member=member, error=None)

    @application.post("/members/<member_id>/sub-account/review")
    def sub_account_review(member_id: str) -> str:
        member = MEMBER_RECORDS.get(member_id)
        if member is None:
            return redirect(url_for("member_not_found", member_id=member_id))
        account_type = request.form.get("account_type", "").strip()
        opening_amount = request.form.get("opening_amount", "").strip()
        try:
            parsed_amount = float(opening_amount)
        except ValueError:
            parsed_amount = -1
        if account_type not in {"holiday", "emergency"} or parsed_amount <= 0:
            form_content = """
<h1>New Sub-Account Request</h1>
<div class="error" role="alert">Account type and a positive opening amount are required.</div>
<p><a href="{{ url_for('sub_account_form', member_id=member.member_id) }}">Return to request</a></p>
"""
            return _render_page("New Sub-Account Request", form_content, member=member), 400
        review_content = """
<h1>Sub-Account Review</h1>
<table>
  <tr><th>Member</th><td>{{ member.full_name }}</td></tr>
  <tr><th>Account type</th><td>{{ account_type }}</td></tr>
  <tr><th>Opening amount</th><td>${{ "%.2f"|format(parsed_amount) }}</td></tr>
</table>
<form method="post" action="{{ url_for('sub_account_confirmation', member_id=member.member_id) }}">
  <input type="hidden" name="account_type" value="{{ account_type }}">
  <input type="hidden" name="opening_amount" value="{{ opening_amount }}">
  <button type="submit">Confirm sub-account request</button>
</form>
"""
        return _render_page("Sub-Account Review", review_content, member=member, account_type=account_type, parsed_amount=parsed_amount, opening_amount=opening_amount)

    @application.post("/members/<member_id>/sub-account/confirmation")
    def sub_account_confirmation(member_id: str) -> str:
        member = MEMBER_RECORDS.get(member_id)
        if member is None:
            return redirect(url_for("member_not_found", member_id=member_id))
        confirmation_content = """
<h1>Sub-Account Confirmation</h1>
<div class="notice" role="status">Sub-account request is ready for processing.</div>
<p>Member: {{ member.full_name }}</p>
<p>Account type: {{ account_type }}</p>
<p>Opening amount: ${{ "%.2f"|format(parsed_amount) }}</p>
"""
        opening_amount = request.form.get("opening_amount", "0")
        return _render_page(
            "Sub-Account Confirmation",
            confirmation_content,
            member=member,
            account_type=request.form.get("account_type", "unknown"),
            parsed_amount=float(opening_amount),
        )

    return application


def _render_page(page_title: str, content: str, **template_values: object) -> str:
    template_values.setdefault("error", None)
    template_values.setdefault("notice", None)
    template_values.setdefault("member_id", "")
    rendered_content = render_template_string(content, **template_values)
    return render_template_string(BASE_TEMPLATE, page_title=page_title, content=rendered_content)


if __name__ == "__main__":
    create_demo_application().run(host="127.0.0.1", port=5001, debug=False)