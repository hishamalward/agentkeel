# Hook payloads, captured

> Codex payloads (CLI 0.160.0, captured 2026-10-04) are in `tests/fixtures/codex/`, with paths scrubbed and the encrypted dispatch message replaced; the facts they pin are in [the hosts page](hosts.md). The Claude Code payloads below are also in `tests/fixtures/claude/`.

Captured 2026-08-23 from a real non-interactive run (`claude -p`, Claude Code 2.1.241) in a throwaway repo whose hooks appended stdin to a file. Paths are scrubbed to `<repo>`. These are the shapes the hooks in `hooks/` parse; nothing here is from memory or from documentation.

## Common envelope

Every event carries `session_id`, `transcript_path`, `cwd`, `prompt_id`, `permission_mode`, `hook_event_name`, `tool_name`, `tool_input`. `cwd` is the directory the session runs in (the same as `CLAUDE_PROJECT_DIR` in the hook's environment for a single-root session). PostToolUse adds `tool_response`.

Exit codes, as observed: `0` allows; `2` blocks the tool call and the hook's stderr is shown to the model as the reason. Anything else is reported but does not block.

## PreToolUse, `Bash`

```
{
  "session_id": "<uuid>",
  "transcript_path": "<home>/.claude/projects/<slug>/<session>.jsonl",
  "cwd": "<repo>",
  "prompt_id": "<uuid>",
  "permission_mode": "default",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "echo captured > note.txt",
    "description": "Write \"captured\" to note.txt"
  },
  "tool_use_id": "toolu_01GP5nSSjpC7b7NjX6w98R2S"
}
```

## PreToolUse, `Write`

```
{
  "session_id": "<uuid>",
  "transcript_path": "<home>/.claude/projects/<slug>/<session>.jsonl",
  "cwd": "<repo>",
  "prompt_id": "<uuid>",
  "permission_mode": "default",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "<repo>/hello.py",
    "content": "print('hi')\n"
  },
  "tool_use_id": "toolu_017hKsoxcTfzGuPjsXXuK4Dz"
}
```

## PreToolUse, `Edit`

```
{
  "session_id": "<uuid>",
  "transcript_path": "<home>/.claude/projects/<slug>/<session>.jsonl",
  "cwd": "<repo>",
  "prompt_id": "<uuid>",
  "permission_mode": "default",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "<repo>/hello.py",
    "old_string": "print('hi')",
    "new_string": "print('hello')",
    "replace_all": false
  },
  "tool_use_id": "toolu_01NkCiG7D3gWiCiE8heVKjXW"
}
```

## PreToolUse, `Agent`

```
{
  "session_id": "<uuid>",
  "transcript_path": "<home>/.claude/projects/<slug>/<session>.jsonl",
  "cwd": "<repo>",
  "prompt_id": "<uuid>",
  "permission_mode": "default",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PreToolUse",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Reply with the word done",
    "prompt": "reply with the single word done",
    "run_in_background": false
  },
  "tool_use_id": "toolu_017Rgnaxy73ozi6xM3nh6KW4"
}
```

## PostToolUse, `Bash`

```
{
  "session_id": "<uuid>",
  "transcript_path": "<home>/.claude/projects/<slug>/<session>.jsonl",
  "cwd": "<repo>",
  "prompt_id": "<uuid>",
  "permission_mode": "default",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "echo captured > note.txt",
    "description": "Write \"captured\" to note.txt"
  },
  "tool_response": {
    "stdout": "",
    "stderr": "",
    "interrupted": false,
    "isImage": false,
    "noOutputExpected": false
  },
  "tool_use_id": "toolu_01GP5nSSjpC7b7NjX6w98R2S",
  "duration_ms": 58
}
```

## PostToolUse, `Write`

```
{
  "session_id": "<uuid>",
  "transcript_path": "<home>/.claude/projects/<slug>/<session>.jsonl",
  "cwd": "<repo>",
  "prompt_id": "<uuid>",
  "permission_mode": "default",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "<repo>/hello.py",
    "content": "print('hi')\n"
  },
  "tool_response": {
    "type": "create",
    "filePath": "<repo>/hello.py",
    "content": "print('hi')\n",
    "structuredPatch": [],
    "originalFile": null,
    "userModified": false
  },
  "tool_use_id": "toolu_017hKsoxcTfzGuPjsXXuK4Dz",
  "duration_ms": 8
}
```

## PostToolUse, `Edit`

```
{
  "session_id": "<uuid>",
  "transcript_path": "<home>/.claude/projects/<slug>/<session>.jsonl",
  "cwd": "<repo>",
  "prompt_id": "<uuid>",
  "permission_mode": "default",
  "effort": {
    "level": "high"
  },
  "hook_event_name": "PostToolUse",
  "tool_name": "Edit",
  "tool_input": {
    "file_path": "<repo>/hello.py",
    "old_string": "print('hi')",
    "new_string": "print('hello')",
    "replace_all": false
  },
  "tool_response": {
    "filePath": "<repo>/hello.py",
    "oldString": "print('hi')",
    "newString": "print('hello')",
    "originalFile": "print('hi')\n",
    "structuredPatch": [
      {
        "oldStart": 1,
        "oldLines": 1,
        "newStart": 1,
        "newLines": 1,
        "lines": [
          "-print('hi')",
          "+print('hello')"
        ]
      }
    ],
    "userModified": false,
    "replaceAll": false
  },
  "tool_use_id": "toolu_01NkCiG7D3gWiCiE8heVKjXW",
  "duration_ms": 6
}
```
