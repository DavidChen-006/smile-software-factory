"""smile audit: merged factory pull requests that no verdict ever approved (contract section 9).

The event log is the record of what the lane judged; GitHub is the record of what landed. Where they
disagree, a human merged something unreviewed, and that is the whole of this command.
"""

import events
import github
import worktree
from mux import Usage

FIELDS = "number,body,mergeCommit,headRefOid"


def cmd_audit(root: str, args: list) -> int:
    if args:
        raise Usage(f"unexpected argument {args[0]}")
    approved = {(r.get("pr"), r.get("sha")) for r in events.read(root)
                if r.get("event") == "review.verdict" and r.get("detail") == "APPROVE"}
    for pr in github.factory_prs(worktree.repo(root), "merged", FIELDS):
        if (pr["number"], pr["headRefOid"]) not in approved:
            print(f"#{pr['number']} {pr['headRefOid']} {pr['bead']}")
    return 0
