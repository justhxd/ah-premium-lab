# Repository Collaboration Guide

## Change Delivery Workflow

For every substantial change, use this fixed loop:

1. Implement the change.
2. Verify it with the most relevant local commands and, when frontend behavior is affected, browser checks.
3. Commit only the files that belong to the change, leaving unrelated user changes untouched.
4. Finish with a short delivery note in Chinese.

The delivery note must include:

- `改了什么`: a concise summary of the actual code or document changes.
- `验证命令`: exact commands that were run, or clearly state when verification was not run.
- `下一步`: the most useful follow-up, or `无` when the work is complete.

If a local service is started for the task, mention its URL only when it is useful to the user; do not include a fixed service address field in every delivery note.

When the working tree already has unrelated changes, do not stage or commit them. Mention that only the files for the current change were included.
