# UX review of the one-page app

Note, 11 October 2026, later the same day: the page has since been translated into Italian and restyled with the Lutech brand (docs/brand.md). Where this review asks for a 736-pixel column, no metric tiles and the numbered steps as the only headings, the new layout replaces it: a column of about 1080 pixels, a stepper, one card per step that closes with a one-line summary, a strip of counts in step 4, and the CSV previews as tables in tabs with the table toolbar hidden. The other findings still apply, and the page keeps them. The quotes below are the English texts of the page at the time of the review.

11 October 2026. Two readers in one: a UX designer, and a Marketing Cloud tester who has never seen the code. The page was started with `streamlit run cjhelper/app.py --server.headless true --server.port 8602` and driven with Playwright in Chromium at 1280 and 900 pixels wide. The inputs were `fixtures/CJ template complesso-v1.json`, a `.txt` file, a `.json` file holding plain text, and `{"entities": {}}`. The yardsticks were the spec's sections "The app" and "Outputs", plus the README.

Screenshots are in `/tmp/claude-0/-home-user-CJ-Test-Helper/47c9992c-056a-5408-a219-f7db1a48a3b0/scratchpad/ux/`. The names below start with `1280-`. The `900-` file with the same name looks the same, because the page keeps a 736-pixel column at both widths. `05c` and `07` exist at 1280 only.

Test conditions: another session was editing `cjhelper/` during the review. While files were changing, two Generate attempts failed with raw Python errors (change 6 uses one of them). Once, during a reload, the result also vanished after a download. That did not happen again once the code had been unchanged for three minutes, so it is not listed as a change. With stable code, the upload is read in under a second and Generate takes 33 to 42 seconds (six runs).

## Verdicts

| Criterion | Verdict | Why |
| --- | --- | --- |
| One obvious path from upload to download | Pass with changes | The four numbered steps come in order with nothing competing, but both actions are grey outline buttons, the run ends without a "done" line, and the download button is 3,970 pixels (4.4 screens) below Generate. |
| Clear errors | Pass with changes | The app's own messages are one plain sentence with nothing else on the page, but a `.txt` file gets a red chip with no sentence, and a failed generation prints the raw Python exception. |
| A restrained look that reads as designed by a person | Pass with changes | One column, no decoration and no dashboard tiles, but stock Streamlit gives it away: the Deploy button and menu, a red checkbox as the only colour, three large heading sizes and twelve identical full-width grey fields. |

## Changes, most important first

Changes 1 to 7 decide the verdicts; changes 8 to 20 are smaller.

1. Step 4, under the summary: add a "Before you import" block saying to open `report.md` first (its "How to run" gives the import order), that only TST_R01_S01 is active in the CSVs, and that scenarios run one at a time, in run order, by switching the activation field, because none of this is on the page today (`1280-04r08-summary.png`, `1280-04r12-download.png`).
2. Step 4, previews: close the five CSV previews by default, one expander per file with `scenarios.csv` first as the run plan, so that the download is about one screen below Generate instead of 3,970 pixels, since each preview shows only 10 rows and the first few of up to 33 columns, mostly placeholders (`1280-04e-result-full.png`, `1280-04r10-preview-of-the-csvs.png`).
3. Step 4, buttons: make "Generate" and "Download the zip" primary buttons and rename the step "4. Generate and download", because both are grey outline buttons today, weaker than the red checkbox above them (`1280-04-before-generate.png`, `1280-04d-download-button.png`).
4. Steps 3 and 4, real inbox: put the real inbox first in the settings with its tooltip text as a visible caption ("Left empty, they get undeliverable addresses and those branches are reported as not covered"), and move the "No real inbox is set" warning from the last of eight warnings into the summary (`1280-03-settings-first-view.png`, `1280-04r11-result-warnings.png`).
5. Step 1, uploader: drop the uploader's file-type filter so that the app's own plain "not valid JSON" sentence answers a `.txt` file, which today gets a red chip with no text and the reason "text/plain files are not allowed." only on hover (`1280-05-not-json-txt.png`, `1280-05c-not-json-txt-hover.png`).
6. Step 4, failures: replace the raw exception ("The generation failed: 'CoverageEngine' object has no attribute '_flag_case_variants'.") with one plain sentence and a closed "Technical details" expander (`1280-07-generation-failed-raw-error.png`).
7. Step 4, preview toolbars: remove the "Download as CSV" icon that each preview shows on hover, because the previews hold only their 10 rows, so it saves a 10-row CSV beside the real zip (`1280-04g-preview-toolbar.png`).
8. Step 4, summary: add the report's explanation under the counts, for example "134 of the 139 branches not covered lie behind 2 branches that no contact can reach (see report.md)", so that 139 beside 120 does not read as a failure (`1280-04r08-summary.png`).
9. Step 4, while it runs: say beside the button how long generation takes (33 to 42 seconds on the pilot), disable the button during the run (it stays clickable today), and end with one plain line such as "Done at 13:45, run identifier R01" (`1280-04a-generating.png`, `1280-04b-result-landing.png`).
10. Step 4, download text: under the list of the seven files, say what each one is for: the four CSVs to import, `scenarios.csv` the run order, `testbook.xlsx` the tests and expected results, and `report.md` the coverage and how to run (`1280-04r12-download.png`).
11. Steps 2 and 4, warnings: write each warning as one sentence-case line, using `report.md`'s groups and wording and leaving the IDs to the report, which means one line for 'DemoSKY' and 'ActionId' instead of two 23-ID bullets, "steps" instead of "step(s)", "Suspicious pattern" capitalised the same way in both lists, and different headings for the two lists that are both called "Warnings" today (`1280-02d-review-warnings.png`, `1280-04r11-result-warnings.png`).
12. Whole page, chrome and theme: hide Streamlit's toolbar (Deploy, the menu, the running-man Stop) with the minimal toolbar mode, and set a neutral primary colour so that a red checkbox is not the only colour on the page (`1280-01-empty.png`, `1280-04a-generating.png`).
13. Whole page, headings: keep the four 36-pixel step headings and turn the eight 28-pixel sub-headings (Activities by type, Tables, Warnings, Summary, Trust checks, Preview of the CSVs, Warnings, Download) into bold labels at body size, so that the numbered steps carry the page (`1280-02-after-upload-first-view.png`, `1280-04r08-summary.png`).
14. Step 3, layout: group the fourteen fields under small labels (contacts, contact details, dates, scenarios and keys), put pairs side by side (the two contact counts, window start and end, the two wait offsets), and fold everything except the inbox and the run identifier into a closed "More settings" expander (`1280-03b-settings-step.png`).
15. Step 3, run identifier: show "Use a new one for each generation" as a visible caption instead of a tooltip, because reusing R01 mixes the evidence of two runs (`1280-03b-settings-step.png`).
16. Step 3, dates: show the format as YYYY-MM-DD HH:MM with today's date as an example instead of the code string %Y-%m-%d %H:%M, and caption the window start and end as "1 day before" and "7 days after the generation time", as `report.md` does, instead of -1 and 7 alone (`1280-03b-settings-step.png`).
17. Step 3, real phone number: when the journey sends nothing to a phone, as in the pilot, say so under the field, so that the tester does not look for a number that will not be used (`1280-03b-settings-step.png`).
18. Step 2, tables: list the four tables that get a CSV first, lead with the report's sentence "4 tables get a CSV: ...", and use the report's role names, because the page says "Written only" and "Split and source" where the report says "written" and "source, split" (`1280-02b-review-step.png`).
19. Step 1, error wording: replace the parser's "(Expecting value at line 1, column 1)" with "problem at line 1, column 1", and end both messages with the next step, for example "Choose the JSON file that Package Manager produces." (`1280-05b-not-json-json-ext.png`, `1280-06-no-journey.png`).
20. Step 1, uploader help: move the "?" text ("The file is read in memory and discarded; nothing is stored.") into a visible caption that also says where the file comes from (`1280-01b-upload-help-tooltip.png`).

## Good, keep as is

- One page, one column, with the four numbered steps in the spec's order, each appearing only once the one before it is done, and an empty page that shows nothing but the upload (`1280-01-empty.png`).
- Step 2 appears in under a second and opens with a plain sentence: "The export holds the journey CJ_SkYDE_NCRM_Demo_final, with 178 activities."
- The app's own errors are one red line with nothing else on the page and steps 2 to 4 hidden (`1280-06-no-journey.png`).
- Static tables with right-aligned counts for the activities, the tables and the summary, with no metric tiles, charts, icons or emoji.
- The settings use the names of the spec and of the report's "Settings used", with every default filled in and the detected activation field named in a plain caption.
- The trust checks: "7 of 7 trust checks passed." followed by the checks in the report's words.
- The zip is named after the journey, the page lists its seven files, and the result stays on the page after the download.
- Sentence case in every heading, label and button, and the summary uses the report's terms (scenarios, cases, contacts, branches covered with manual action).
- The same 736-pixel column at 1280 and 900, with no horizontal page scroll; only the previews scroll sideways, inside their frames.
