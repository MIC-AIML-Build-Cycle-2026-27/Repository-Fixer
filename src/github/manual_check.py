"""Try the GitHub client against a real repository (read-only unless --comment is used).

    python -m src.github.manual_check owner/repo 1
    python -m src.github.manual_check owner/repo 1 --comment "Hello from Repository Fixer"
"""

import argparse
import sys

from src.github.client import get_github_client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("issue", type=int)
    parser.add_argument("--comment", help="also post this comment on the issue")
    args = parser.parse_args()

    client = get_github_client()
    if client is None:
        sys.exit("Set a real GITHUB_TOKEN in .env first.")

    with client:
        print("Default branch:", client.get_default_branch(args.repo))
        issue = client.get_issue(args.repo, args.issue)
        print("Issue title:", issue.title)
        print("Issue body:", issue.body[:300] or "(empty)")
        if args.comment:
            client.comment_on_issue(args.repo, args.issue, args.comment)
            print("Comment posted.")


if __name__ == "__main__":
    main()
