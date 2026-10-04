# Guida: verifica del set di riferimento (gold set)

## Di cosa si tratta?
Il nostro programma legge gli atti parlamentari dai PDF e annota ciò che vi è scritto (domanda, risposta, decisione ...). Per sapere quanto sia affidabile, alcune persone controllano a mano un campione. Le sue risposte formano il "gold set": il metro con cui misuriamo il programma. Il suo lavoro determina quindi direttamente quanto sia credibile il nostro risultato.

## Cosa serve
- Un computer con l'ambiente Python (venv) e il progetto. I dati sono già stati preparati da Alexander: non deve scaricare nulla.
- Un browser (Chrome, Firefox, Edge). Lo strumento funziona solo sul suo computer, senza internet.

## Come iniziare
1. Apra il terminale nella cartella del progetto e attivi il venv.
2. Prima, per provare (nulla conta, i dati veri restano intatti):
   `openparl-extract review --demo`
3. Quando si sente sicura/o, per il lavoro vero:
   `openparl-extract review`
4. Si apre il browser. In alto scelga la lingua (DE / IT / EN), inserisca il **suo nome**, poi clicchi su "Iniziamo".
5. Per terminare: Ctrl+C nel terminale.

## Come si presenta una domanda
A sinistra vede la pagina del PDF. Il punto da cui il programma ha preso il valore è evidenziato in **giallo**. A destra c'è **una** domanda, sotto il testo trovato dal programma e grandi pulsanti di risposta. In alto vede l'avanzamento ("Domanda 5 di 40").

### I tre casi tipici
1. **Il valore è giusto.** Clicchi **Corretto**.
2. **Il valore è sbagliato**, il documento dice altro. Clicchi **Sbagliato**. Appare quindi il passaggio facoltativo "Indichi il valore giusto (facoltativo)": clicchi sul punto giusto della pagina (diventa blu), scriva poche parole, scelga il pulsante della decisione giusta oppure inserisca la data, poi clicchi su **Conferma**. Se non desidera correggere, clicchi **Salta** (oppure prema Invio): la risposta "Sbagliato" viene salvata comunque.
3. **Il programma non ha trovato nulla, ma nel documento c'è.** La domanda è ad esempio "Nel documento c'è una risposta del governo?". Clicchi **Sì**, poi sul punto giusto della pagina (diventa blu) e su **Conferma**. Oppure scriva poche parole. Per una decisione scelga il pulsante giusto, per una data inserisca la data.
   Se nel documento non c'è davvero: **No**.

### Cosa significa "Non è nel documento"?
Il programma ha indicato un valore, ma nel documento non c'è **da nessuna parte** (inventato). È diverso da "Sbagliato": con "Sbagliato" l'informazione esiste, ma è diversa.

### Quando "Non so (più tardi)"?
Quando dopo poco non riesce a decidere (ad es. scansione illeggibile). La domanda ritorna alla fine. Non tiri a indovinare.

## Cosa vedo, cosa clicco

| Cosa vede | Cosa clicca |
|---|---|
| Valore del programma, corrisponde al documento | Corretto |
| Valore del programma, il documento dice altro | Sbagliato, poi (facoltativo) il punto giusto sulla pagina e Conferma, oppure Salta |
| Valore del programma, nel documento non c'è | Non è nel documento |
| "C'è ...?" e nel documento c'è | Sì, poi il punto sulla pagina, Conferma |
| "C'è ...?" e nel documento non c'è | No |
| Non lo sa | Non so (più tardi) |
| Ha cliccato per errore | Annulla (o tasto Z) |

## Tastiera
- **1, 2, 3, 4**: i pulsanti dall'alto in basso (il numero è scritto sul pulsante)
- **Z**: Annulla
- **Invio**: Conferma (quando indica il valore giusto; senza inserimento dopo "Sbagliato" = Salta), **Esc**: interrompe l'inserimento

## Quanto tempo ci vuole?
Basta circa 1 ora al giorno. Ogni risposta viene **salvata subito in automatico** (compare brevemente "Salvato"). Può smettere in qualsiasi momento e riprendere esattamente da dove era rimasta/o.

## Annulla
Con **Annulla** ritira la sua ultima risposta; cliccando più volte torna ancora indietro. Se nel frattempo un'altra persona ha risposto alla stessa domanda, non è più possibile (vedrà un messaggio). In tal caso continui semplicemente.

## Per favore non
- Non eseguire `gold-prefill` mentre l'app è aperta.
- Non modificare a mano i file gold.
- Usare sempre il proprio nome (non quello di un'altra persona).
- Non tenga premuto un tasto: potrebbe rispondere a domande per errore.
- Non usare l'app in due schede del browser contemporaneamente.

## Domande?
Chieda ad Alexander (chat del progetto). Annoti brevemente i casi poco chiari, meglio con documento e domanda.
