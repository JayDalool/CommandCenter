"""Claude's own question tool (AskUserQuestion), sent to Jay through CommandCenter instead of the pane.

Jay (2026-11-16): an agent that asks with Claude's built-in prompt stops until he is back at the workspace. Its
questions belong in Slack, answered by number or in his own words, and the agent carries on once they are answered.

scripts/cc-ask-hook is a Claude Code PreToolUse hook for AskUserQuestion (installed into ~/.claude/settings.json by
scripts/install-claude-commands.sh, which go-live runs). It hands the questions to ccd (POST /api/hooks/ask), which
finds the session among herdr's agents:

- a ticket's task session: the questions become the ticket's questions (pipeline.ask), so they reach Slack and the
  ticket in CommandCenter, and the answers are typed back into that session (Daemon.task_answers);
- a project's lead or the CTO: the questions go to that conversation in Messages (and so to its Slack thread), and
  Jay's reply comes back as the usual Messages nudge;
- anything else, or ccd not answering: nothing is routed and Claude shows its own prompt, as before.

When ccd routed them, the hook denies the tool call with a reason Claude reads: where the questions went and that it
should end its turn and wait.
"""
import json
import sys

MAX_QUESTIONS = 4        # what AskUserQuestion sends at most; more is not a call from Claude's tool
OPTION_MAX = 200         # pipeline.ask: an option is at most 200 characters
QUESTION_MAX = 1000      # pipeline.ask: a question is at most 1000
OPTIONS_MAX = 8          # pipeline.ask: at most 8 options


def _clean(text):
    return " ".join(str(text or "").split())


def _cut(text, n):
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def questions_of(raw):
    """AskUserQuestion's `questions` as pipeline.ask questions: [{text} | {text, options}], or [] when it is not
    that shape. An option is its label, then its description; a pick-several question says so in its text."""
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_QUESTIONS:
        return []
    out = []
    for q in raw:
        if not isinstance(q, dict):
            return []
        text = _clean(q.get("question"))
        if not text:
            return []
        if q.get("multiSelect") is True:
            text += " (pick one or more)"
        options = []
        for o in q.get("options") or []:
            if not isinstance(o, dict):
                return []
            label, desc = _clean(o.get("label")), _clean(o.get("description"))
            if label:
                options.append(_cut(f"{label}: {desc}" if desc else label, OPTION_MAX))
        q2 = {"text": _cut(text, QUESTION_MAX)}
        if len(options) >= 2:
            q2["options"] = options[:OPTIONS_MAX]
        out.append(q2)
    return out


def lead_text(questions):
    """The questions as one Messages message from a lead: numbered, each choice's options numbered under it."""
    several = len(questions) > 1
    lines = ["Questions for you:" if several else "A question for you:", ""]
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. {q['text']}" if several else q["text"])
        for j, o in enumerate(q.get("options") or [], 1):
            lines.append(f"   {j}) {o}")
        lines.append("")
    lines.append("Reply with numbered lines (1. …, 2. …): an option's number or your own words." if several
                 else "Reply with an option's number or your own words.")
    return "\n".join(lines)


def deny(reason):
    """The PreToolUse answer that stops the tool call and tells Claude why."""
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": reason}}


def main(stdin=None, stdout=None, call=None):
    """The hook. Always exits 0: a hook that fails must leave Claude's own prompt working."""
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        event = json.load(stdin)
    except ValueError:
        return 0
    if not isinstance(event, dict) or event.get("tool_name") != "AskUserQuestion":
        return 0
    if call is None:
        from .pipeline_cli import call
    body = {"sessionId": event.get("session_id"), "questions": (event.get("tool_input") or {}).get("questions")}
    try:
        code, out = call("POST", "/api/hooks/ask", body, "agent:ask-hook")
    except Exception:  # noqa: BLE001 — no token file, a bad port: Claude's own prompt
        return 0
    if code or not isinstance(out, dict) or not out.get("routed") or not out.get("say"):
        return 0
    stdout.write(json.dumps(deny(str(out["say"]))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
