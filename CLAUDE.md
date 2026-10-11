# CJ Test Helper PoC

- docs/spec.md is the source of truth. If something is unclear or contradictory, stop and ask.
- Follow the "Development priorities" order in the spec. Do not start a level until the previous one passes on the pilot.
- Never invent Salesforce behaviour. Anything not in the spec is an assumption: list it in the report, do not hard-code it silently.
- Pilot input: fixtures/CJ template complesso-v1.json. The acceptance criteria in the spec are the definition of done.
- The old tool (github.com/carolagalloni/CJ-Test-Helper) is reference only. Where it differs from the spec, the spec wins.
- Python 3.11+, tests with pytest, one commit per completed step.
