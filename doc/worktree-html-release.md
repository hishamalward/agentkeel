Coding-task HTML now lives in the worktree’s root-level `/doc` folder. A separate spec/full-plan page is optional; the progress page is rewritten in place. Visual guidance asks for concrete mockups and leaves the layout to the agent.

No-code tasks keep their worktree-free flow, with temporary or provider-managed HTML outside the repository. Coding-task handoffs use page digests and file contents so verification does not force another HTML edit. Cleanup verifies that committed pages are preserved in canonical `/doc` before deleting the worktree.

Validation: full regression suite, focused real-Git delivery and no-code guard tests, hook selftests, documentation/release checks, and desktop/mobile HTML inspection. Live host Stop invocation remains unverified.
