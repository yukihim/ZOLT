"""
tools.py — ZOLT GitHub MCP Tool Definitions

Rich, small-model-optimized tool schemas that override the sparse definitions
returned by MCPHost.get_tools_json(). Each tool has:
  - Trigger phrases in `description` so the model knows WHEN to call it
  - Negative examples to prevent confusion between similar tools
  - All parameters documented with types, constraints, and defaults
  - `required` arrays kept minimal so the model doesn't refuse to call due to missing optional fields

Usage in agent.py:
    from .tools import GITHUB_TOOLS
    # Replace: tools = self.mcp_host.get_tools_json() or None
    # With:    tools = GITHUB_TOOLS
"""

from __future__ import annotations

# ── Helpers ──────────────────────────────────────────────────────────────────

def _owner() -> dict:
    return {"type": "string", "description": "GitHub username or org. Default: 'yukihim'. Omit to use default."}

def _repo() -> dict:
    return {"type": "string", "description": "Repository name. Default: 'ZOLT'. Omit to use default."}

def _ref() -> dict:
    return {"type": "string", "description": "Branch name, tag, or commit SHA. Default: 'main'."}

def _per_page() -> dict:
    return {"type": "integer", "description": "Max results to return. Default: 10. Max: 100."}


# ── Tool Definitions ──────────────────────────────────────────────────────────

GITHUB_TOOLS: list[dict] = [

    # ── REPOSITORY ────────────────────────────────────────────────────────────

    {
        "type": "function",
        "function": {
            "name": "get_file_contents",
            "description": (
                "READ-ONLY. Fetch the raw contents of an existing file in a GitHub repo. "
                "Use when the user says: 'show me the code in X', 'what's in file Y', "
                "'read config Z', 'show me the README', 'open this file'. "
                "You MUST know the exact file path. If unsure of the path, call list_directory first. "
                "Do NOT use this to create or write files — use create_or_update_file for that. "
                "Do NOT use this if the user said 'create', 'write', 'save', or 'add a file'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "path":  {
                        "type": "string",
                        "description": (
                            "File path relative to the repo root. "
                            "Examples: 'README.md', 'src/main.py', 'config/settings.json'. "
                            "Required."
                        )
                    },
                    "ref":   _ref(),
                },
                "required": ["owner", "repo", "path"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and subdirectories at a given path in the repo tree. "
                "Use when the user asks: 'what files are in X folder', "
                "'show the project structure', 'what's in the src directory'. "
                "Also use this BEFORE calling get_file_contents if you don't know the exact path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "path":  {
                        "type": "string",
                        "description": "Directory path relative to repo root. Use '' or '.' for the root. Default: ''."
                    },
                    "ref":   _ref(),
                },
                "required": ["owner", "repo"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "search_repositories",
            "description": (
                "Search GitHub for public repositories matching a query. "
                "Use when the user asks: 'find repos about X', 'search for Y library', "
                "'any GitHub projects for Z'. "
                "Do NOT use for searching code inside a repo — use search_code instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string. Supports GitHub qualifiers like 'language:python'. Required."
                    },
                    "per_page": _per_page(),
                },
                "required": ["query"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "create_repository",
            "description": (
                "Create a new GitHub repository under the authenticated user's account. "
                "Use ONLY when the user explicitly says: 'create a repo', 'make a new repository', "
                "'initialize a GitHub project named X'. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string", "description": "Repository name. Required. No spaces — use hyphens."},
                    "description": {"type": "string", "description": "Short description of the repository. Optional."},
                    "private":     {"type": "boolean", "description": "True for private, False for public. Default: False."},
                    "auto_init":   {"type": "boolean", "description": "Initialize with a README. Default: True."},
                },
                "required": ["name"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "fork_repository",
            "description": (
                "Fork an existing repository into the authenticated user's account. "
                "Use when the user says: 'fork this repo', 'fork owner/repo', 'make a fork of X'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "organization": {"type": "string", "description": "Fork into an org instead of the user account. Optional."},
                },
                "required": ["owner", "repo"],
            },
        },
    },

    # ── FILE OPERATIONS ───────────────────────────────────────────────────────

    {
        "type": "function",
        "function": {
            "name": "create_or_update_file",
            "description": (
                "WRITE. Create a new file or overwrite an existing file in the repo. "
                "Use when the user says: 'create file X', 'write to Y', 'update this file', "
                "'save changes to Z', 'add a file named X with content Y'. "
                "Do NOT use this to read a file — use get_file_contents for that. "
                "REQUIRED fields: path, message, content. Never omit `message` — use a short commit message like 'Add final_polish.txt' if the user didn't specify one. "
                "To UPDATE an existing file you MUST also provide the current file's SHA "
                "(get it first via get_file_contents). "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner":   {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":    {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "branch":  {"type": "string", "description": "Target branch. ALWAYS include. Use 'main' unless told otherwise."},
                    "path":    {"type": "string", "description": "File path relative to repo root. Example: 'final_polish.txt', 'src/main.py'."},
                    "message": {"type": "string", "description": "Commit message. Example: 'Add final_polish.txt'. If the user did not specify one, invent a short descriptive message."},
                    "content": {"type": "string", "description": "Full UTF-8 file content as plain text (NOT base64)."},
                    "sha":     {"type": "string", "description": "Current file SHA - required ONLY when updating an existing file. Omit when creating a brand-new file."},
                },
                "required": ["owner", "repo", "branch", "path", "message", "content"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "push_files",
            "description": (
                "Push multiple files to the repo in a single commit. "
                "Use when the user wants to commit several files at once: "
                "'push these files', 'commit all these changes', 'batch update these files'. "
                "Prefer this over multiple create_or_update_file calls when >1 file changes. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "branch":  {"type": "string", "description": "Target branch. Required."},
                    "message": {"type": "string", "description": "Commit message. Required."},
                    "files": {
                        "type": "array",
                        "description": "List of files to push. Required.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path":    {"type": "string", "description": "File path relative to repo root."},
                                "content": {"type": "string", "description": "Full file content as a UTF-8 string."},
                            },
                            "required": ["owner", "repo", "branch", "message", "files"],
                        },
                    },
                },
                "required": ["branch", "message", "files"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": (
                "Delete a single file from the repo. "
                "Use ONLY when the user explicitly says: 'delete file X', 'remove Y from the repo'. "
                "You MUST fetch the file's SHA via get_file_contents before calling this. "
                "SENSITIVE: requires user approval. This action is irreversible without a restore."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "path":    {"type": "string", "description": "File path relative to repo root. Required."},
                    "message": {"type": "string", "description": "Commit message. Required."},
                    "sha":     {"type": "string", "description": "Current file SHA. Required. Get via get_file_contents."},
                    "branch":  {"type": "string", "description": "Branch to delete from. Default: 'main'."},
                },
                "required": ["owner", "repo", "path", "message", "sha"],
            },
        },
    },

    # ── CODE SEARCH ───────────────────────────────────────────────────────────

    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search for a keyword or pattern across all files in a repo. "
                "Use when the user asks: 'where is X defined', 'find usages of Y', "
                "'which file contains Z', 'search for function foo'. "
                "Do NOT use for issue/PR searches. Do NOT use if you already know the file path — use get_file_contents instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Search query. To scope to a repo use 'KEYWORD repo:owner/repo'. "
                            "Example: 'async def login repo:yukihim/ZOLT'. Required."
                        )
                    },
                },
                "required": ["query"],
            },
        },
    },

    # ── COMMITS ───────────────────────────────────────────────────────────────

    {
        "type": "function",
        "function": {
            "name": "list_commits",
            "description": (
                "List recent commits on a branch with author, timestamp, and message. "
                "Use when the user asks: 'latest commit', 'recent changes', 'what was committed', "
                "'commit history', 'what changed recently', 'show git log', 'all commits so far'. "
                "Do NOT use to get diff details — use get_commit for that. "
                "IMPORTANT: Only include optional params if the user specified them. "
                "Never pass empty strings — omit the field entirely if you have no value."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner":    {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":     {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "sha":      {"type": "string", "description": "Branch name or commit SHA to start from. Omit to use the default branch. Do NOT pass empty string."},
                    "path":     {"type": "string", "description": "Only include if filtering by file path. Omit entirely otherwise. Do NOT pass empty string."},
                    "author":   {"type": "string", "description": "Only include if filtering by a specific author. Omit entirely otherwise. Do NOT pass empty string."},
                    "per_page": {"type": "integer", "description": "Max results to return as an INTEGER (not a string). Default: 10. Max: 100."},
                },
                "required": ["owner", "repo"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_commit",
            "description": (
                "Get full details of a single commit: message, author, timestamp, and per-file diffs. "
                "Use when the user provides a specific commit hash like 'commit abc123' "
                "or when you need the full diff after calling list_commits."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "sha":    {"type": "string", "description": "Full or short commit SHA. Required."},
                },
                "required": ["owner", "repo", "sha"],
            },
        },
    },

    # ── BRANCHES ──────────────────────────────────────────────────────────────

    {
        "type": "function",
        "function": {
            "name": "list_branches",
            "description": (
                "List all branches in the repository. "
                "Use when the user asks: 'what branches exist', 'show branches', 'list all branches'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "per_page": _per_page(),
                },
                "required": ["owner", "repo"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "create_branch",
            "description": (
                "Create a new branch from an existing branch or commit SHA. "
                "Use when the user says: 'create branch X', 'make a new branch called Y', "
                "'branch off from main into Z'. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "branch": {"type": "string", "description": "Name for the new branch. Required."},
                    "from_branch": {"type": "string", "description": "Source branch or SHA to branch from. Default: 'main'."},
                },
                "required": ["owner", "repo", "branch"],
            },
        },
    },

    # ── ISSUES ────────────────────────────────────────────────────────────────

    {
        "type": "function",
        "function": {
            "name": "list_issues",
            "description": (
                "List GitHub issues with title, number, labels, and assignees. "
                "Use when the user asks: 'open issues', 'bug reports', 'what issues exist', "
                "'show tickets', 'any problems reported'. "
                "Do NOT use to fetch a single issue — use get_issue for that."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "state":    {"type": "string", "enum": ["open", "closed", "all"], "description": "Default: 'open'."},
                    "labels":   {"type": "string", "description": "Comma-separated label names to filter by. Optional."},
                    "assignee": {"type": "string", "description": "Filter by GitHub username. Use 'none' for unassigned. Optional."},
                    "sort":     {"type": "string", "enum": ["created", "updated", "comments"], "description": "Default: 'created'."},
                    "direction":{"type": "string", "enum": ["asc", "desc"], "description": "Default: 'desc'."},
                    "per_page": _per_page(),
                },
                "required": ["owner", "repo"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_issue",
            "description": (
                "Get full details of a single issue: title, body, labels, assignees, "
                "comment count, and open/closed status. "
                "Use when the user mentions a specific issue number like '#42' or 'issue 7'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "issue_number": {"type": "integer", "description": "The issue number (e.g., 42). Required."},
                },
                "required": ["owner", "repo", "issue_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "create_issue",
            "description": (
                "Create a new GitHub issue. Use when the user says: "
                "'open an issue', 'file a bug', 'create a ticket', 'report this problem'. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "title":     {"type": "string", "description": "Short issue title. Required."},
                    "body":      {"type": "string", "description": "Full issue description in Markdown. Optional but recommended."},
                    "labels":    {"type": "array", "items": {"type": "string"}, "description": "Label names to apply. Optional."},
                    "assignees": {"type": "array", "items": {"type": "string"}, "description": "GitHub usernames to assign. Optional."},
                    "milestone": {"type": "integer", "description": "Milestone number to associate. Optional."},
                },
                "required": ["owner", "repo", "issue_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "update_issue",
            "description": (
                "Update an existing issue: change title, body, state, labels, or assignees. "
                "Use when the user says: 'close issue #N', 'reopen issue #N', 'edit issue #N', "
                "'relabel issue', 'reassign issue'. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "issue_number": {"type": "integer", "description": "Issue number to update. Required."},
                    "title":        {"type": "string", "description": "New title. Optional."},
                    "body":         {"type": "string", "description": "New body content. Optional."},
                    "state":        {"type": "string", "enum": ["open", "closed"], "description": "Set to 'closed' to close the issue. Optional."},
                    "labels":       {"type": "array", "items": {"type": "string"}, "description": "Replace all labels with this list. Optional."},
                    "assignees":    {"type": "array", "items": {"type": "string"}, "description": "Replace all assignees with this list. Optional."},
                    "milestone":    {"type": "integer", "description": "Milestone number, or null to clear. Optional."},
                },
                "required": ["owner", "repo", "issue_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "add_comment_to_issue",
            "description": (
                "Post a comment on an existing issue or pull request. "
                "Use when the user says: 'comment on issue #N', 'reply to issue', 'add a note to ticket #N'. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "issue_number": {"type": "integer", "description": "Issue or PR number to comment on. Required."},
                    "body":         {"type": "string", "description": "Comment text in Markdown. Required."},
                },
                "required": ["owner", "repo", "issue_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "search_issues",
            "description": (
                "Search issues and PRs across GitHub by keyword, label, author, or state. "
                "Use when the user asks: 'find issues about X', 'any bug reports mentioning Y', "
                "'search for closed issues labeled Z'. "
                "Do NOT use for fetching a specific numbered issue — use get_issue instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "GitHub issue search query. Supports qualifiers: "
                            "is:issue, is:pr, is:open, is:closed, label:X, author:Y, repo:owner/repo. "
                            "Example: 'login bug is:open repo:yukihim/ZOLT'. Required."
                        )
                    },
                    "per_page": _per_page(),
                },
                "required": ["query"],
            },
        },
    },

    # ── PULL REQUESTS ─────────────────────────────────────────────────────────

    {
        "type": "function",
        "function": {
            "name": "list_pull_requests",
            "description": (
                "List pull requests with title, number, author, and merge status. "
                "Use when the user asks: 'open PRs', 'pending merges', 'what PRs are there', "
                "'review queue', 'any pull requests'. "
                "Do NOT use to get details of a single PR — use get_pull_request instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "state":    {"type": "string", "enum": ["open", "closed", "all"], "description": "Default: 'open'."},
                    "head":     {"type": "string", "description": "Filter by head branch in format 'user:branch'. Optional."},
                    "base":     {"type": "string", "description": "Filter by base branch name. Optional."},
                    "sort":     {"type": "string", "enum": ["created", "updated", "popularity", "long-running"], "description": "Default: 'created'."},
                    "direction":{"type": "string", "enum": ["asc", "desc"], "description": "Default: 'desc'."},
                    "per_page": {"type": "integer", "description": "Max results as an INTEGER. Default: 10."},
                },
                "required": ["owner", "repo"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_pull_request",
            "description": (
                "Get full details of a single pull request: title, body, diff stats, "
                "reviewers, merge status, and CI check summary. "
                "Use when the user mentions a specific PR like 'PR #12' or 'pull request 5'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "pull_number": {"type": "integer", "description": "The pull request number. Required."},
                },
                "required": ["owner", "repo", "pull_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "create_pull_request",
            "description": (
                "Create a new pull request. Use when the user says: "
                "'open a PR', 'create a pull request from X to Y', 'submit changes for review'. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "title":  {"type": "string", "description": "PR title. Required."},
                    "body":   {"type": "string", "description": "PR description in Markdown. Optional."},
                    "head":   {"type": "string", "description": "The branch containing the changes (source). Required."},
                    "base":   {"type": "string", "description": "The branch to merge into (target). Default: 'main'."},
                    "draft":  {"type": "boolean", "description": "True to create as a draft PR. Default: False."},
                },
                "required": ["owner", "repo", "title", "head"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "update_pull_request",
            "description": (
                "Update an existing pull request: change title, body, state, or base branch. "
                "Use when the user says: 'edit PR #N', 'close PR #N', 'update pull request description'. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "pull_number": {"type": "integer", "description": "PR number to update. Required."},
                    "title":       {"type": "string", "description": "New title. Optional."},
                    "body":        {"type": "string", "description": "New description. Optional."},
                    "state":       {"type": "string", "enum": ["open", "closed"], "description": "Set to 'closed' to close the PR. Optional."},
                    "base":        {"type": "string", "description": "Change the target base branch. Optional."},
                },
                "required": ["owner", "repo", "pull_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "merge_pull_request",
            "description": (
                "Merge an open pull request into its base branch. "
                "Use ONLY when the user explicitly says: 'merge PR #N', 'merge pull request #N', 'approve and merge'. "
                "NEVER call speculatively. Always confirm the PR number before calling. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "pull_number":    {"type": "integer", "description": "PR number to merge. Required."},
                    "commit_title":   {"type": "string", "description": "Custom merge commit title. Optional."},
                    "commit_message": {"type": "string", "description": "Custom merge commit body. Optional."},
                    "merge_method":   {
                        "type": "string",
                        "enum": ["merge", "squash", "rebase"],
                        "description": "How to merge. 'squash' combines all commits into one. Default: 'squash'."
                    },
                },
                "required": ["owner", "repo", "pull_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_pull_request_files",
            "description": (
                "List all files changed in a pull request with their diff stats. "
                "Use when the user asks: 'what files does PR #N change', 'show the diff for PR #N', "
                "'what did this PR touch'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "pull_number": {"type": "integer", "description": "PR number. Required."},
                },
                "required": ["owner", "repo", "pull_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "get_pull_request_reviews",
            "description": (
                "List all review decisions on a pull request: approved, changes requested, or commented. "
                "Use when the user asks: 'who reviewed PR #N', 'is PR #N approved', "
                "'what did reviewers say about PR #N'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                                       "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "pull_number": {"type": "integer", "description": "PR number. Required."},
                },
                "required": ["owner", "repo", "pull_number"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "create_pull_request_review",
            "description": (
                "Submit a review on a pull request: approve, request changes, or comment. "
                "Use when the user says: 'approve PR #N', 'request changes on PR #N', "
                "'leave a review on PR #N'. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "pull_number": {"type": "integer", "description": "PR number. Required."},
                    "event":       {
                        "type": "string",
                        "enum": ["APPROVE", "REQUEST_CHANGES", "COMMENT"],
                        "description": "Review action. Required."
                    },
                    "body":        {"type": "string", "description": "Review comment text. Required for REQUEST_CHANGES and COMMENT."},
                },
                "required": ["owner", "repo", "pull_number", "event"],
            },
        },
    },

    # ── GIT REFS (revert / reset / tag) ──────────────────────────────────────

    {
        "type": "function",
        "function": {
            "name": "get_ref",
            "description": (
                "Get the current SHA a Git ref (branch or tag) points to. "
                "Use this to look up what commit HEAD or a branch currently points at. "
                "Example ref formats: 'heads/main', 'heads/feature-x', 'tags/v1.0'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "ref":   {"type": "string", "description": "Ref path WITHOUT 'refs/' prefix. Examples: 'heads/main', 'heads/dev', 'tags/v1.0'. Required."},
                },
                "required": ["owner", "repo", "ref"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "update_ref",
            "description": (
                "Move a branch pointer to a different commit SHA. "
                "This is the ONLY correct tool for: 'revert to commit X', 'reset branch to SHA Y', "
                "'undo last N commits', 'go back to the first commit', 'hard reset main to X'. "
                "WORKFLOW for revert: (1) call list_commits to find the target SHA, "
                "(2) call update_ref with that SHA and force=true. "
                "Do NOT use create_pull_request or any other tool for reverting. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "ref":   {"type": "string", "description": "Ref path WITHOUT 'refs/' prefix. Example: 'heads/main'. Required."},
                    "sha":   {"type": "string", "description": "The full commit SHA to point the branch at. Required. Get this from list_commits or get_commit."},
                    "force": {"type": "boolean", "description": "Must be true when moving the branch backwards (revert/reset). Default: true."},
                },
                "required": ["owner", "repo", "ref", "sha"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "create_ref",
            "description": (
                "Create a new Git ref (branch or tag) pointing at a specific commit SHA. "
                "Use for: 'tag this commit as v1.0', 'create a tag at SHA X', "
                "'create a branch from commit Y'. "
                "For creating branches from existing branches use create_branch instead. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "ref":   {"type": "string", "description": "Full ref path WITH 'refs/' prefix. Examples: 'refs/heads/new-branch', 'refs/tags/v1.0'. Required."},
                    "sha":   {"type": "string", "description": "The commit SHA this ref should point to. Required."},
                },
                "required": ["owner", "repo", "ref", "sha"],
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "delete_ref",
            "description": (
                "Delete a Git ref (branch or tag). "
                "Use when the user says: 'delete branch X', 'remove tag Y', 'clean up branch Z'. "
                "Do NOT use to delete files — use delete_file for that. "
                "SENSITIVE: requires user approval before execution."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string", "description": "GitHub username or org. ALWAYS include. Use 'yukihim' unless told otherwise."},
                    "repo":  {"type": "string", "description": "Repository name. ALWAYS include. Use 'ZOLT' unless told otherwise."},
                    "ref":   {"type": "string", "description": "Ref path WITHOUT 'refs/' prefix. Examples: 'heads/my-branch', 'tags/v1.0'. Required."},
                },
                "required": ["owner", "repo", "ref"],
            },
        },
    },
]