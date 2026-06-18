"""First-subscribe welcome sample (§5)."""

from __future__ import annotations

from app.models import utcnow


def test_first_subscription_sends_welcome_sample(client, db, make_user, auth, sent_emails):
    ann = make_user("a@example.com", "Ann A.", verified_at=utcnow())
    bob = make_user("b@example.com", "Bob B.")
    carol = make_user("c@example.com", "Carol C.")
    h = auth(ann)

    client.post("/subscriptions", json={"feeder_id": bob.id}, headers=h)
    welcomes = [e for e in sent_emails if "welcome" in e["subject"].lower()]
    assert len(welcomes) == 1
    assert welcomes[0]["to"] == "a@example.com"

    # A second subscription does NOT re-send the welcome.
    client.post("/subscriptions", json={"feeder_id": carol.id}, headers=h)
    welcomes = [e for e in sent_emails if "welcome" in e["subject"].lower()]
    assert len(welcomes) == 1
