"""Heading patterns per section. Accent-free, lower-case, matched at the START of normalised text.

Extend here; every entry is a regex fragment (alternatives joined with |).
"""
import re

_RAT = r"(?:regierungsrat|bundesrat|stadtrat|gemeinderat|staatsrat|kantonsrat|grosser rat|grossrat|landrat|rat)(?:es|s)?"

_RAW: dict[str, list[str]] = {
    "executive_answer": [
        r"antwort des " + _RAT, r"stellungnahme(?: des " + _RAT + r")?",
        r"reponse(?: du (?:conseil (?:d'etat|federal|communal|municipal|general)|gouvernement))?",
        r"avis du conseil \w+(?: d'etat)?",
        r"risposta(?: del (?:consiglio (?:di stato|federale|comunale)|municipio|governo))?",
        r"parere del consiglio \w+(?: di stato)?",
    ],
    "justification": [
        r"begru?e?ndung", r"erlaeu?terung(?:en)?", r"erlauterung(?:en)?",
        r"developpement", r"expose des motifs", r"motivation", r"justification",
        r"motivazione|motivazioni", r"sviluppo", r"giustificazione", r"considerando",
    ],
    "questions": [
        r"fragen", r"wir fragen", r"der regierungsrat wird gebeten.*fragen",
        r"questions", r"le conseil d'etat est prie de repondre",
        r"domande", r"si chiede",
        # ZH Anfrage evidence: no heading, only an intro sentence before the questions
        r"(?:vor diesem hintergrund )?(?:bitten|ersuchen) wir .*beantwortung folgender fragen",
    ],
    "decision": [
        r"beschluss(?:fassung|entwurf)?", r"entscheid", r"dispositiv", r"beschliesst", r"antrag (?:an|des|der) ",
        r"der (?:landrat|grosse rat|kantonsrat|rat|grossrat|gemeinderat|stadtrat) beschliesst",
        r"decision", r"decret", r"arrete", r"le grand conseil decide", r"le conseil \w+ decide",
        r"decisione", r"decreto", r"risoluzione", r"il gran consiglio (?:decreta|decide)",
    ],
    "affair_text": [
        r"anfrage", r"vorstoss", r"motion", r"postulat", r"interpellation", r"kleine anfrage",
        r"text des vorstosses", r"wortlaut", r"eingereichter text",
        r"texte depose", r"texte de l'intervention",
        r"testo depositato", r"testo", r"proposition de (?:motion|resolution|postulat)", r"depot et developpement",
        r"a n f r a g e", r"i n t e r p e l l a t i o n", r"mozione", r"postulato", r"interpellanza", r"interrogazione",
    ],
}

# Bare common nouns: open a section only if block type is heading or the line is short
# and does not end with "." (see rules.heading_section).
_BARE_RAW = {
    "executive_answer": [r"antwort"],
    "annex": [r"anhang|anhange|anhaenge", r"beilagen?", r"anlagen?", r"annexes?", r"allegati|allegato"],
}
BARE_PATTERNS: dict[str, re.Pattern] = {
    k: re.compile(r"(?:" + "|".join(v) + r")\b") for k, v in _BARE_RAW.items()
}

# order matters on ties: more specific sections first
PATTERNS: dict[str, re.Pattern] = {
    k: re.compile(r"(?:" + "|".join(v) + r")\b") for k, v in _RAW.items()
}
