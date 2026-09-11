from automation.demo_app import create_demo_application


def test_member_lookup_reaches_detail_page() -> None:
    client = create_demo_application().test_client()

    response = client.post("/members/search", data={"member_id": "12345"})

    assert response.status_code == 302
    assert response.location.endswith("/members/12345")
    detail_response = client.get(response.location)
    assert b"Member Details" in detail_response.data
    assert b"$1,240.50" in detail_response.data


def test_unknown_member_is_a_business_outcome() -> None:
    client = create_demo_application().test_client()

    response = client.post("/members/search", data={"member_id": "99999"}, follow_redirects=True)

    assert response.status_code == 200
    assert b"Member not found" in response.data


def test_invalid_member_id_returns_validation_error() -> None:
    client = create_demo_application().test_client()

    response = client.post("/members/search", data={"member_id": "12"})

    assert response.status_code == 400
    assert b"exactly five digits" in response.data


def test_sub_account_flow_reaches_review_and_confirmation() -> None:
    client = create_demo_application().test_client()

    review_response = client.post(
        "/members/12345/sub-account/review",
        data={"account_type": "holiday", "opening_amount": "25.00"},
    )
    assert review_response.status_code == 200
    assert b"Sub-Account Review" in review_response.data

    confirmation_response = client.post(
        "/members/12345/sub-account/confirmation",
        data={"account_type": "holiday", "opening_amount": "25.00"},
    )
    assert confirmation_response.status_code == 200
    assert b"Sub-Account Confirmation" in confirmation_response.data


def test_sub_account_validation_error_is_explicit() -> None:
    client = create_demo_application().test_client()

    response = client.post(
        "/members/12345/sub-account/review",
        data={"account_type": "holiday", "opening_amount": "not-money"},
    )

    assert response.status_code == 400
    assert b"positive opening amount" in response.data


def test_simulated_dialog_is_visible() -> None:
    client = create_demo_application().test_client()

    response = client.get("/members/12345?simulate=dialog")

    assert response.status_code == 200
    assert b'role="dialog"' in response.data
    assert b"Session notice" in response.data