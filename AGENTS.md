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
- `服务地址`: the local URL when a frontend/backend service is running; otherwise write `无`.
- `下一步`: the most useful follow-up, or `无` when the work is complete.

When the working tree already has unrelated changes, do not stage or commit them. Mention that only the files for the current change were included.
