# CJ Test Helper PoC

- docs/spec.md is the source of truth. If something is unclear or contradictory, stop and ask.
- Follow the "Development priorities" order in the spec. Do not start a level until the previous one passes on the pilot.
- Never invent Salesforce behaviour. Anything not in the spec is an assumption: list it in the report, do not hard-code it silently.
- Pilot input: fixtures/CJ template complesso-v1.json. The acceptance criteria in the spec are the definition of done.
- The old tool (github.com/carolagalloni/CJ-Test-Helper) is reference only. Where it differs from the spec, the spec wins.
- Python 3.11+, tests with pytest, one commit per completed step.

## Look and language of the app (UI work only)

- Any change to how the Streamlit page looks follows docs/brand.md (Lutech brand: colours, Montserrat, logo use, page structure, tone of the texts). Read it before touching cjhelper/app.css, .streamlit/config.toml, cjhelper/static/ or the texts in cjhelper/app.py.
- The page is in Italian; Salesforce terms and words the team uses in English (journey, split, branch, trust check, warning, inbox...) stay in English. The generator's own messages (warnings, trust checks, loader errors, CLI) and the texts of the downloaded files (report.md, testbook.xlsx) are in Italian too, following the glossary in docs/brand.md; file names, scenarios.csv and testbook column headers, export identifiers and generated values stay in English. The documents under docs/ are in Italian too, except docs/spec.md (source of truth, kept as written); docstrings and code comments stay in English.
- Styling is presentation only: never change generation logic, settings or outputs to make the page look different.
- cjhelper/app.css must never contain a less-than sign, even in a comment: Streamlit's HTML sanitizer drops the whole stylesheet without an error.
- Check a visual change in a real browser (streamlit run cjhelper/app.py from the repository root) and keep tests/test_app.py in step with the page.
