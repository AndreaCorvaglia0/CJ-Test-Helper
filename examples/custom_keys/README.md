# custom_keys

The contact key is not `ContactId` and the scenario join is not `CampaignName`; the join fields also have
**different names on the two sides**. Builder: `examples/build_fresh_examples.py`, `build_custom_keys`.

## Tables and contact model

```
DE_Entry     SubscriberKey (PK, sendable field), Emailaddress, WaveRef (not null)
DE_Customer  CustNo (PK, sendable field), Emailaddress, MobilePhone, WaveRef (not null), Tier Text(10)
DE_Wave      WaveCode (PK), CHANNEL Text(10) not null, ACTIVE Boolean not null
group -> DE_Customer (CustNo) -> DE_Entry (CustNo = SubscriberKey) -> DE_Wave (WaveRef = WaveCode)
```

Entry query: `SELECT C.CustNo AS SubscriberKey, C.Emailaddress, W.WaveCode AS WaveRef FROM [DE_Customer] C
JOIN [DE_Wave] W ON C.WaveRef = W.WaveCode WHERE W.ACTIVE = 'True'`.

Journey: SPLIT-1 "Channel" (DE_Wave.CHANNEL: `Email` -> SPLIT-2, `SMS` -> UPDATE-2, remainder -> UPDATE-3);
SPLIT-2 "Gold tier" (DE_Customer.Tier Equal `Gold` -> UPDATE-4, remainder -> UPDATE-5).

## Expected answer, step by step

1. **Contact key**: the entry table's sendable field `SubscriberKey` (docs/export-format.md: "that field is
   the contact key").
2. **Levels** (step 3): `DE_Customer` joins the entry on the contact key (`CustNo = SubscriberKey`):
   contact-level. `DE_Wave` is joined on `WaveRef = WaveCode`, "any other field": **scenario-level**.
3. **Scenarios**: SPLIT-1's three outcomes need three different CHANNEL values (`Email`, `SMS`, other), one
   per scenario: **3 scenarios**.
4. **Cases**: terminals UPDATE-4 (`Email`, Tier `Gold`), UPDATE-5 (`Email`, Tier not `Gold`), UPDATE-2
   (`SMS`), UPDATE-3 (other): **4 cases, 12 contacts**. All 5 branches covered.

## Not asserted (checked by hand in the review)

- Keys (spec, Keys): `TST_R01_C0001`... in `DE_Customer.CustNo` and `DE_Entry.SubscriberKey`;
  `TST_R01_S01`... in `DE_Wave.WaveCode`, `DE_Entry.WaveRef` and `DE_Customer.WaveRef` ("written into the
  field that joins contacts to the scenario-level table").
- `ACTIVE` = `True` on the first scenario only ("one active scenario"), entry rows = query output.
