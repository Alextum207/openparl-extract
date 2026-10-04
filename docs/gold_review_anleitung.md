# Anleitung: Gold-Set prüfen

## Worum geht es?
Unser Programm liest Vorstösse aus Parlaments-PDFs und schreibt auf, was darin steht (Frage, Antwort, Entscheid ...). Damit wir wissen, wie zuverlässig das ist, prüfen Menschen eine Stichprobe von Hand. Ihre Antworten bilden das "Gold-Set": die Messlatte, an der wir das Programm messen. Ihre Arbeit entscheidet also direkt, wie glaubwürdig unser Ergebnis ist.

## Was Sie brauchen
- Einen Computer mit Python-Umgebung (venv) und das Projekt. Die Daten hat Alexander schon vorbereitet, Sie müssen nichts herunterladen.
- Einen Browser (Chrome, Firefox, Edge). Das Tool läuft nur auf Ihrem Rechner, es braucht kein Internet.

## So starten Sie
1. Terminal im Projektordner öffnen, venv aktivieren.
2. Zuerst zum Üben (nichts davon zählt, Ihre echten Daten bleiben unberührt):
   `openparl-extract review --demo`
3. Wenn Sie sicher sind, für die echte Arbeit:
   `openparl-extract review`
4. Der Browser öffnet sich. Oben rechts Sprache wählen (DE / IT / EN), Ihren **eigenen Namen** eingeben, auf "Los geht's" klicken.
5. Beenden: im Terminal Ctrl+C.

## Wie eine Frage aussieht
Links sehen Sie die PDF-Seite. Die Stelle, aus der das Programm seinen Wert hat, ist **gelb** markiert. Rechts steht **eine** Frage, darunter der vom Programm gefundene Text und grosse Antwort-Knöpfe. Oben sehen Sie den Fortschritt ("Frage 5 von 40").

### Die drei typischen Fälle
1. **Der Wert stimmt.** Klicken Sie **Richtig**.
2. **Der Wert ist falsch**, im Dokument steht etwas anderes. Klicken Sie **Falsch**. Danach erscheint der freiwillige Schritt "Den richtigen Wert angeben (freiwillig)": Klicken Sie die richtige Stelle auf der Seite an (sie wird blau), tippen Sie ein paar Worte ein, wählen Sie den passenden Entscheid-Knopf oder geben Sie das Datum ein, und klicken Sie auf **Bestätigen**. Wenn Sie nicht korrigieren möchten, klicken Sie **Überspringen** (oder drücken Sie Enter): Ihre Antwort "Falsch" wird trotzdem gespeichert.
3. **Das Programm hat nichts gefunden, im Dokument steht es aber.** Die Frage lautet dann z. B. "Gibt es im Dokument eine Antwort der Regierung?". Klicken Sie **Ja**, dann auf die richtige Stelle auf der Seite (sie wird blau) und auf **Bestätigen**. Oder tippen Sie ein paar Worte ein. Bei einem Entscheid wählen Sie den passenden Knopf, bei einem Datum geben Sie das Datum ein.
   Steht es wirklich nicht im Dokument: **Nein**.

### Was heisst "Steht nicht im Dokument"?
Das Programm hat einen Wert angegeben, aber er steht **nirgends** im Dokument (erfunden). Das ist etwas anderes als "Falsch": bei "Falsch" gibt es die Information, nur anders.

### Wann "Unsicher"?
Wenn Sie es nach kurzer Zeit nicht entscheiden können (z. B. unleserlicher Scan). Die Frage kommt am Schluss nochmals. Raten Sie nicht.

## Was sehe ich, was klicke ich?

| Was Sie sehen | Was Sie klicken |
|---|---|
| Wert vom Programm, passt zum Dokument | Richtig |
| Wert vom Programm, Dokument sagt etwas anderes | Falsch, dann (freiwillig) die richtige Stelle anklicken und Bestätigen, oder Überspringen |
| Wert vom Programm, steht nirgends im Dokument | Steht nicht im Dokument |
| "Gibt es ...?" und es gibt es im Dokument | Ja, dann Stelle anklicken, Bestätigen |
| "Gibt es ...?" und es gibt es nicht | Nein |
| Sie wissen es nicht | Unsicher (später) |
| Sie haben sich verklickt | Rückgängig (oder Taste Z) |

## Tastatur
- **1, 2, 3, 4**: die Knöpfe von oben nach unten (die Zahl steht auf dem Knopf)
- **Z**: Rückgängig
- **Enter**: Bestätigen (beim Angeben des richtigen Werts; ohne Eingabe bei "Falsch" = Überspringen), **Esc**: Abbrechen

## Wie lange dauert es?
Etwa 1 Stunde pro Tag genügt. Jede Antwort wird **sofort automatisch gespeichert** ("Gespeichert" erscheint kurz). Sie können jederzeit aufhören und später genau dort weitermachen.

## Rückgängig
Mit **Rückgängig** nehmen Sie Ihre letzte Antwort zurück; mehrmals klicken geht weiter zurück. Hat inzwischen jemand anderes dieselbe Frage beantwortet, geht es nicht mehr (Sie sehen eine Meldung). Dann einfach weitermachen.

## Bitte nicht
- Nicht `gold-prefill` ausführen, solange die App offen ist.
- Die Gold-Dateien nicht von Hand ändern.
- Immer den eigenen Namen verwenden (nicht den einer anderen Person).
- Halten Sie keine Taste gedrückt, sonst werden Fragen versehentlich beantwortet.
- Die App nicht in zwei Browser-Tabs gleichzeitig benutzen.

## Fragen?
Alexander fragen (Projekt-Chat). Bitte unklare Fälle kurz notieren, am besten mit Dokument und Frage.
