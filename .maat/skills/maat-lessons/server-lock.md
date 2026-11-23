# The server lock: the maintainer's steps

1. **Give the agent its own GitHub identity.** Use a fine-grained personal
   access token on a separate account, or a GitHub App. Grant contents write
   on non-protected branches only. Grant no admin. A merge or a push to the
   protected branch under that identity is then refused by GitHub itself.
2. **Use it only in agent sessions.** The agent's sessions authenticate with
   that identity. The maintainer's own token stays out of them.
3. **No bypass.** The ruleset has `bypass_actors: []`. Nobody, the
   maintainer included, is listed as able to skip it.
4. **Check for drift.** Run
   `"${CLAUDE_PLUGIN_ROOT}/bin/maat-audit" docs/maat/charter.yaml`. It reads the live ruleset and repo settings with `gh api` and
   prints each difference from the charter. Exit 0 means no drift. Drift
   between written and enforced policy is the failure every field study
   reports, so run it after any change to the repo settings.
