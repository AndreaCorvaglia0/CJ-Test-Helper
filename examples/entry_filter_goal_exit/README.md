# entry_filter_goal_exit

Un journey con un **filtro di ingresso**, un **goal** e un **exit criterion**, tre costrutti che il generatore non
modella. Data extension di ingresso Run Once; il filtro è scritto sull'event definition (`arguments.criteria`,
`metaData.criteriaDescription`) e sul trigger (`configurationArguments.criteria` e un `filterDefinitionId` diverso
dal GUID di soli zeri); `goals` ed `exits` del journey hanno un elemento ciascuno con un criterio. Le forme di goal ed
exit sono inventate (gli export visti hanno le due liste vuote): il test non dipende dai loro campi interni.

## Journey

```
SPLIT-1 "Opt-in"   Event.Optin Is true  -> UPDATE-1 "Opted in"
                   remainder            -> UPDATE-2 "Not opted in"

filtro di ingresso   Segment Equal 'Premium'
goal                 "Premium purchase": Segment Equal 'Bought'
exit criterion       "Unsubscribed":     Segment Equal 'Out'
```

Tabelle: `DE_GE_Entry` (`SubscriberKey`, `EmailAddress`, `Segment` Text, `Optin` Boolean, ammettono null),
`DE_GE_Log` (solo scritta).

## Risposta attesa, passo per passo

1. **Copertura.** Spec, "Entry source and procedure": "Entry filters, goals and exit criteria are not modelled". La
   copertura è quindi quella del solo SPLIT-1: `Optin` `True` -> UPDATE-1, `False` (preferito a null) -> UPDATE-2.
   **1 scenario, 2 casi, 6 contatti**, entrambi i branch **coperti**. Nessun valore di `Segment` è scelto per
   soddisfare il filtro: è proprio il motivo per cui va segnalato.
2. **Segnalazione.** Stessa frase: "when present they are reported, because contacts may not enter or may leave
   early". Quindi report.md nomina tutti e tre: il filtro di ingresso (si accetta "filtro di ingresso" o "entry
   filter"), il goal ("goal" o "obiettivo") e l'exit criteria ("exit criteria", "criteri di uscita" o "criterio di
   uscita"). Il controllo è su tre testi separati: se il generatore ne segnala solo uno o due, il messaggio dice quale
   manca.

## Non verificato

- Dove il report li dice (warning, sezione dedicata, riepilogo) e con quale frase: la spec dice solo "reported".
- Il testbook: la spec non fissa se anche il testbook li nomina.
