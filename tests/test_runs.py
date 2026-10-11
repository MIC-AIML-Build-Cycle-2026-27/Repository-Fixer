from src.db.models import Run


def test_get_run_returns_summary(client, db_session):
    db_session.add(Run(repo_full_name="org/repo", issue_number=3))
    db_session.commit()

    response = client.get("/runs/1")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 1
    assert body["repo_full_name"] == "org/repo"
    assert body["issue_number"] == 3
    assert body["status"] == "queued"
    assert body["pr_url"] is None


def test_get_unknown_run_is_404(client):
    assert client.get("/runs/999").status_code == 404


def test_list_runs_newest_first(client, db_session):
    db_session.add_all(
        [Run(repo_full_name="a/b", issue_number=1), Run(repo_full_name="a/b", issue_number=2)]
    )
    db_session.commit()

    response = client.get("/runs")

    assert response.status_code == 200
    assert [r["issue_number"] for r in response.json()] == [2, 1]
