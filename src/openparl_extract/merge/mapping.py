"""Mapping tables from OpenParlData metadata vocabularies to our controlled vocabularies.

Every entry is backed by evidence recorded in docs/metadata_mapping.md. Anything without evidence is NOT mapped:
types become `other`, events and roles are skipped with a review flag.
"""
import re

from openparl_extract.models import ActorRole, AffairType, Level, ProceduralState

# affairs.type_harmonized_id (group_by/types_harmonized, 17 ids + null)
HARMONIZED_TYPE_TO_AFFAIR_TYPE: dict[int, AffairType] = {
    2: AffairType.motion,                       # Motion
    3: AffairType.postulate,                    # Postulat
    4: AffairType.parliamentary_initiative,     # Parlamentarische Initiative
    7: AffairType.popular_initiative,           # Volksinitiative
    8: AffairType.interpellation,               # Interpellation
    12: AffairType.written_question,            # Anfrage / Question / Interrogazione
}  # not mapped on purpose (-> other): 1 Diverses, 5 Vernehmlassung, 6 Wahl, 9 Regierungsgeschaeft, 10 Fragestunde,
#   11 Petition, 13 Ergaenzungsantrag, 14 Einbuergerung, 15 Informationsdokument, 16 Bericht, 17 Genehmigungsbeschluss

# contributors[].role_harmonized.en. "Author" is lossy (also used for co-signatories): see AUTHOR_COSIGNER_RE.
PERSON_ROLE_TO_ACTOR_ROLE: dict[str, ActorRole] = {
    "Author": ActorRole.submitter,
    "Cosign": ActorRole.co_signatory,
    "Speaker": ActorRole.spokesperson,
    "Leading Department": ActorRole.executive_respondent,
    "Assigned Committee": ActorRole.committee,
    "Committee": ActorRole.committee,
}  # unmapped seen: "Council Initial" (a chamber), "Departement" (Mitbeteiligtes Departement)

# verbatim contributors[].role of harmonized "Author" entries that are co-signers, not first submitters
# cosignataire / cofirmatario are plain French / Italian-singular translations of evidenced terms (Mitunterzeichner, Cofirmatari)
AUTHOR_COSIGNER_RE = re.compile(r"mitunterzeichn|zweitunterzeichn|drittunterzeichn|cofirmatar|mitvorst\w*ss|miteinreich"
                                r"|cosignatair", re.IGNORECASE)
# verbatim roles of harmonized "Author" that are evidenced first submitters; anything else is ambiguous
AUTHOR_SUBMITTER_RE = re.compile(r"erstunterzeichn|urheber|presentat|auteur|hauptvorst\w*ss", re.IGNORECASE)

# events[].title_harmonized_id. Ids without clear evidence (24 Agenda, 29/32/76 proposals, 47, 67) are skipped + flagged.
EVENT_TO_PROCEDURAL_STATE: dict[int, ProceduralState] = {
    1: ProceduralState.submitted,    # Eingereicht
    6: ProceduralState.answered,     # Beantwortet
    8: ProceduralState.debated,      # Behandelt vom Parlament
    60: ProceduralState.debated,     # Im Parlament behandelt
    26: ProceduralState.referred,    # Ueberwiesen
    27: ProceduralState.referred,    # Referred Postulate
    28: ProceduralState.referred,    # Transferred to committee
    35: ProceduralState.decided,     # Abgelehnt
    38: ProceduralState.decided,     # Erledigt / Kenntnisnahme (Done)
    36: ProceduralState.written_off, # Abgeschrieben
    40: ProceduralState.withdrawn,   # Zurueckgezogen
}

# Fallback for events without title_harmonized_id (all federal events): verbatim label, lower-case, de/fr/it as observed
# in the same events' title dict (CHE sample, 2026-10-05). Only labels whose German form equals a mapped id above.
EVENT_LABEL_TO_PROCEDURAL_STATE: dict[str, ProceduralState] = {
    "eingereicht": ProceduralState.submitted, "déposé": ProceduralState.submitted, "depositato": ProceduralState.submitted,
    "erledigt": ProceduralState.decided, "liquidé": ProceduralState.decided, "liquidato": ProceduralState.decided,
}

# bodies[].type; "country" is only federal for CHE (the body list also holds ~248 foreign countries)
BODY_TYPE_TO_LEVEL: dict[str, Level] = {
    "country": Level.federal,
    "canton": Level.cantonal,
    "municipality": Level.municipal,
    "city": Level.municipal,
}
