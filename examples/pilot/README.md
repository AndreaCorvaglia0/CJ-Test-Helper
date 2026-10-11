# pilot

The spec's "Acceptance criteria on the pilot journey", encoded as far as `expected.json` allows. The
package is the real export: `"package": "../../fixtures/CJ template complesso-v1.json"`. Settings: defaults
(text comparison case-sensitive) plus a real inbox, because the acceptance criteria say "Contacts needing
an open or click use the real inbox".

Notation: `Dn` = `MULTICRITERIADECISIONV2-n`, `ENGn` = `ENGAGEMENTSPLITV2-n`, `R1` = `RANDOMSPLITV2-1`,
`C.` = `DE_NCRM_AD_HOC_CONFIG` (scenario-level), `M.` = `SF_Master_DataExtension_DE` (contact-level).

## Acceptance criteria -> expected.json

| Spec criterion | expected.json |
| --- | --- |
| "The journey `CJ_SkYDE_NCRM_Demo_final` is parsed with all 178 activities and no crash." | `journey_name`, `activity_count: 178` |
| "Exactly four CSVs are produced: Entry, Master, Target, Config." | `csv_tables` (4 names) |
| Levels (spec: "Master is contact-level, and Config is scenario-level because it is joined on `CampaignName`") | `table_levels` |
| "Each CSV has the exact columns ...", "Every Target row joins ...", "Every Entry row matches what the entry query would return." | `checks_pass: true` |
| "Every reachable branch of the 106 decision splits is covered by at least one case of 3 contacts." | `branches` (decision outcomes), `cases[*].contact_count` |
| "The four engagement Yes branches after channels 2 and 3 are reported as unreachable, because all six engagement splits reference the first email." | `ENG3`..`ENG6` `branchResult-1`: not covered, `reason_contains: "unreachable"` |
| "The 90/10 random split has a statistical case of 50 contacts." | `R1` outcomes `statistical: true`; the case with `contact_count: 50` and `random` 1..9 |
| "For reference, the earlier hand-built tool reported 40 path scenarios plus 1 statistical, 148 cases and 494 contacts on this journey; the PoC should land in the same range." | `scenario_count`, `case_count`, `contact_count` ranges, see "Counts" (they cannot match under the default setting) |
| Report lists "the same value written in two letter cases (`Email` and `EMAIL` in the pilot)" | `warnings_contain: ["Email", "EMAIL"]` |
| Not expressible: real inbox vs `@example.invalid` per contact, testbook, "Running twice ... gives the same scenarios, cases and keys" | see `examples/README.md`, format gaps |

## How the branch statuses were derived

The graph was dumped with a small script (activity key, type, name, and for every outcome its label,
criteria and `next`) and read by hand. Its shape:

```
D1  "control group required" C.Control Group Required Is true -> R1 ; remainder -> D2
R1  90% -> D2 ; 10% -> UPDATECONTACTDATAV2-1 -> WAITBYDURATION-2 -> exit
D2  "Channel1"   C.CHANNEL1  Email -> D3 | DM -> D7 | OB -> D9 | SMS -> D11 | remainder -> exit
    D3/D7/D9/D11 IGNOREPERM1 Is false -> consent split D4/D8/D10/D12 ; remainder -> send
    EMAILV2-1 is on D3 remainder and on D4 true, i.e. ONLY when CHANNEL1 = 'Email'
    every channel-1 leaf -> WAITBYATTRIBUTE-1 -> D5
D5  "Open/Click strategy" Open_Click_Strategy Is false -> D13 ; remainder (true) -> D6
D6  "channel 1 email?" CHANNEL1 Equal 'Email' -> ENG1 ; remainder -> D13
ENG1 open EMAILV2-1:  Yes -> ENG2 (click EMAILV2-1: Yes -> exit, No -> exit) ; No -> D61 "Channel2" -> D62..D69 -> exits
D13 "Channel2"   C.CHANNEL2  Email/DM/OB/SMS -> D14..D21 -> WAITBYATTRIBUTE-2 ; remainder -> WAITBYDURATION-3 -> exit
D22 "Open/Click strategy" false -> D23 ; remainder (true) -> D42
D42 "channel 2 email?" CHANNEL2 Equal 'EMAIL' -> ENG3 ; remainder -> D23
ENG3 open EMAILV2-1:  Yes -> ENG4 (click EMAILV2-1: Yes -> D70, No -> D97) ; No -> D106   (D70/D97/D106 "Channel3" -> exits)
D23 "Channel 3"  C.CHANNEL3  Email/DM/OB/SMS -> D24..D31 -> WAITBYATTRIBUTE-3 (DM with IGNOREPERM1 true or Mailing consent true exits) ; remainder -> exit
D32 "Open/Click strategy" false -> D33 ; remainder (true) -> D116
D116 "channel 3 email?" CHANNEL3 Equal 'EMAIL' -> ENG5 ; remainder -> D33
ENG5 open EMAILV2-1:  Yes -> ENG6 (click EMAILV2-1: Yes -> D117, No -> D144) ; No -> D153  (D117/D144/D153 "Channel4", first outcome 'EMAIL' -> exits)
D33 "Channel 4"  C.CHANNEL4  Email/DM/OB/SMS -> D34..D41 -> exits ; remainder -> WAITBYDURATION-6 -> exit
```

Rules used: spec step 2, "Outcomes are tried in order, the first true one wins, and the remainder branch
means none matched"; the default "Text comparisons ignore letter case | Off" ("The PoC assumes they are
different by default"); "Engagement split, reachability | The Yes branch counts as reachable only if the
path sent the referenced email earlier. Otherwise it is reported as unreachable."; "A click needs a link";
"Random split | ... branches reachable only through it get a statistical case of 50 contacts".

1. **D42 `default_path_1` (CHANNEL2 Equal 'EMAIL') is unreachable.** D42 is reached only through
   WAITBYATTRIBUTE-2, which is reached only from D13's `Email`, `DM`, `OB`, `SMS` outcomes (D13's
   remainder exits). So at D42, CHANNEL2 is one of `Email`, `DM`, `OB`, `SMS`, and none equals `EMAIL`
   case-sensitively. Everything behind this outcome is unreachable: **ENG3, ENG4 (both outcomes each), D70-D78,
   D97-D105, D106-D114 (every outcome)**.
2. **D116 `default_path_1` (CHANNEL3 Equal 'EMAIL') is unreachable**, by the same argument: D116 is behind
   WAITBYATTRIBUTE-3, reached only from D23's `Email`/`DM`/`OB`/`SMS` outcomes (D70, D97, D106 lead to
   exits, not to WAITBYATTRIBUTE-3). Behind it: **ENG5, ENG6, D117-D125, D144-D152, D153-D161**.
3. **Why the channel-2/3 engagement Yes branches are unreachable even when case is ignored** (the
   acceptance criterion's reason): EMAILV2-1 is sent only when CHANNEL1 = `Email` (D2 -> D3 -> D4/EMAILV2-1).
   D42 and D116 are behind the `Open_Click_Strategy` = true outcomes of D22/D32, and with that value the
   only way into D13 is D6's remainder, i.e. CHANNEL1 is not `Email`. So every path reaching ENG3 or ENG5
   never sent EMAILV2-1: their Yes branches are unreachable, and ENG4/ENG6 lie behind those Yes branches.
   Under the default setting step 1-2 already make ENG3-ENG6 unreachable as a whole, so all their
   outcomes are listed as not covered with `reason_contains: "unreachable"`.
4. **Everything else among the decision splits is reachable**: each remaining outcome has a value of its
   field that selects it on a path reaching the split (the routing to each split depends only on
   scenario-level values, and `IGNOREPERMx` true routes skip the consent splits), so all of them are
   **covered**, with `statistical: false` (each is reachable through D1's remainder, which avoids R1;
   spec: "The cover prefers paths that avoid it").
5. **ENG1** (reached with CHANNEL1 = `Email` and `Open_Click_Strategy` = true; EMAILV2-1 is sent when
   IGNOREPERM1 is true or "MP email" D4 is true): **Yes = covered with manual action** (real inbox set),
   **No = covered**.
6. **ENG2** (click on EMAILV2-1, whose asset "Demo Sky" has no link): **Yes = not covered,
   `reason_contains: "link"`** (spec: "A click needs a link. When the email referenced by a click split has
   no link, as in the pilot, the Yes branch is reported as not covered"). **No = covered with manual
   action**: ENG2 is only reached after an open at ENG1.
7. **R1**: both outcomes **covered, `statistical: true`**; only reachable through R1. **D1 `default_path_1`:
   covered** (crossed with certainty by the 50 contacts before they reach R1); its statistical flag is not
   asserted.

Totals in `branches`: 256 of the 259 split outcomes; 137 not covered (128 decision outcomes, 8 engagement
outcomes of ENG3-ENG6, and ENG2 Yes), 117 covered, 2 covered with manual action.

### Branches left out (cannot be decided by hand)

`D3/default_path_1`, `D3/remainder_path`, `D4/default_path_1`. They are reachable, so they are covered in
some way, but each can be crossed both by the open case (EMAILV2-1 is sent on D3 remainder and on D4 true)
and by cases without a manual action. Whether the generator's chosen cases include one without a manual
action depends on its cover, so "covered" vs "covered with manual action" cannot be fixed in advance (see
the status convention in `examples/README.md`). Every other branch has the same status under any valid
cover: for example D2 `Email`, D5 remainder and D6 `Email` are also crossed by the ENG1-No cases, which
need no manual action and must exist to cover D61.

### Cross-check

An independent exhaustive simulation (the test engineer's own throw-away script, not part of the repo:
all 109,760 scenario-level combinations x the 8 contact classes, spec rules as above) gives exactly these
statuses for all 256 listed branches, and 8 contact classes, matching the spec ("8 classes in the pilot").

## Counts

**Scenarios >= 23.** (a) D61 is reached only with CHANNEL1 = `Email` and `Open_Click_Strategy` = true. It
has 9 "leaves" (its remainder, and `Email`/`DM`/`OB`/`SMS` each followed by an IGNOREPERM2 split with two
outcomes); one scenario fixes CHANNEL2 and IGNOREPERM2, so it crosses one leaf: 9 scenarios. (b) The other
scenarios reach D13. D33 also has 9 leaves (CHANNEL4 x IGNOREPERM4, remainder): 9 scenarios reaching D33.
Two leaves of D23 never reach D33 (`DM` with IGNOREPERM1 true, and D23's remainder): 2 more; D13's
remainder exits: 1 more. (c) D2's remainder exits at once: 1 more. These groups need disjoint scenarios
(group (a) has CHANNEL1 = `Email` and strategy true, which never reaches D13; group (c) never reaches D13).
22 deterministic scenarios, plus 1 for the statistical case (it needs `Control Group Required` = `True`,
every deterministic case needs `False`) = **23**. A greedy scenario cover reaches 23 or 24.

**Cases >= 33.** Every path ends after exactly one "terminal" outcome (an outcome followed by an exit
without another split). Under the default setting 32 terminal outcomes are reachable without the random
split (D2 remainder; ENG2 No; D61 remainder and 4 x 3 below it; D13 remainder; D23 remainder, D26
remainder, D27 true; D33 remainder and 4 x 3 below it), so at least 32 deterministic cases, plus the
statistical case = **33**. **Contacts >= 32 x 3 + 50 = 146.**

**Upper bounds 30 / 70 / 260** are a sanity margin, not a derivation: the minimal cover gives 23 / 33 / 146;
keeping every distinct path of each chosen scenario as a case (one reading of "each distinct combination
of contact-level values and manual actions is one case") gives about 57-66 cases, 218-245 contacts.

**These ranges are far below the earlier tool's 41 / 148 / 494.** The earlier tool compared text
case-insensitively (spec: "the earlier tool assumed they are equal"). Case-insensitively, D42 and D116 open
two more channel regions; the proven minimum becomes exactly 40 + 1 scenarios, which is the earlier tool's
figure. See `examples/pilot_case_insensitive`. With the default setting the PoC cannot "land in the same
range": this is a contradiction inside the spec, reported to the lead.

## Cases asserted

- The statistical case: `Control Group Required` = `True`, 50 contacts, `random` on `RANDOMSPLITV2-1`
  with the accepted range 1 to 9 (spec: "1 to 9 contacts on the 10% side").
- An open case: CHANNEL1 = `Email`, `Open_Click_Strategy` = `True`, `manual_actions: ["open"]`, ending at
  ENG2 (ENG2 No must be covered, is reachable only after an open, and has no `next`).
- The D2 remainder case: ends at `MULTICRITERIADECISIONV2-2` (its remainder has no `next`).

## Other expectations

- `unsupported: []`: all 178 activities have supported types (106 decision, 6 engagement, 1 random,
  13 waits, 7 send-time waits, 11 emails, 34 update contact).
- `csv_tables`: the spec's table "Applied to the pilot journey": `DE_NCM_AdHoc_Entry`,
  `SF_Master_DataExtension_DE`, `DE_NCRM_AD_HOC_CONFIG`, `DE_NCRM_AdHoc_Target` get a CSV; the log, the
  backup and `DE_Check_Active_Campaigns` do not.
- `table_levels`: Target is contact-level because it joins Master on `ContactId = SalesforceId`, the
  contact key (spec step 3: "joined to the entry on the contact key").
