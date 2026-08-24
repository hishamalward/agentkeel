# Post draft (owner edits before posting)

I asked an AI coding agent to finish a feature and then ship it: checkout main, fast-forward
merge, push.

It did the feature. It declared the work medium, branched, added the flag, ran the check and
pasted the output, got one review round, committed with explicit paths. Then it ran the ship
command, and this came back before any of it executed:

```
WRITE PATH GUARD: refusing a push that moves main.
Finishing the work and shipping it are two decisions; the second is the human's.
When asked, run it with AGENTKEEL_ALLOW_PUSH_MAIN=1 so the override is on record.
```

The agent's report ended with "G4 is your call".

That is the whole point. The rule "do not merge or push unless asked" was in the instructions
the entire time. Rules in a prompt are advice at the start of a session; the session that drifts
is the one that read them. A hook is the same rule at the moment it is about to be broken, with
the reason handed back to the model, and an override that is loud enough to show up in the
transcript when a human really did ask.

I extracted this from how I ship a product with agents writing the code, and made it public:
three invariants, work priced by size as state the hooks can read, four gates with named owners,
and six small hooks with no dependencies. The worked example in the README is six refusals from
a real run. One of them found a bug in a hook.

github.com/hishamalward/agentkeel
