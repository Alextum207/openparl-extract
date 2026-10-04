# OpenParlData metadata -> schema mapping (evidence)

Observed live on api.openparldata.ch (2026-10-04) and in `docs/openparldata_openapi.json`. Fixtures: `tests/fixtures/merge/`.
Mapping tables live in `src/openparl_extract/merge/mapping.py`; unknown values are never guessed (type -> `other`,
event/role -> skipped + review flag `unmapped_event:<label>` / `unmapped_role:<label>`).

## Fetching relations
`GET /v1/affairs/{id}?expand=docs,events,contributors` (comma separated; `all`/`*` also documented) returns each relation as
`{"data": [...], "meta": {...}}` (page size 100, `meta.has_more`). Persons are called **`contributors`**, not persons.
Empty relations come back as `null`. Federal (CHE) affairs often have no `docs`; docs[].`language` was `null` in every sample,
so the document language falls back to the languages in the `title` dict. With several (federal, bilingual cantons) the flag
`language_ambiguous:<keys>` is set and stopword detection on the parsed text decides (`language_detected:<lang>`), else the fixed order de, fr, it, rm.

## Affair fields
`number`, `title` (dict by lang), `title_long`, `begin_date`/`end_date` (ISO datetime), `type_name` (verbatim dict, often
only the source language), `type_harmonized_id` + `type_harmonized` (dict de/fr/it/rm/en), `state_name` and
`state_name_harmonized` (both usually `{}`; not used), `url_external` (dict).

## type_harmonized_id (group_by/types_harmonized, whole corpus)
2 Motion, 3 Postulat, 4 Parlamentarische Initiative, 7 Volksinitiative, 8 Interpellation, 12 Anfrage/Question/Interrogazione
-> mapped. Not mapped (-> `other`, label kept in `original_type_label`): 1 Diverses, 5 Vernehmlassung, 6 Wahl, 9 Regierungsgeschaeft,
10 Fragestunde, 11 Petition, 13 Ergaenzungsantrag, 14 Einbuergerung, 15 Informationsdokument, 16 Bericht,
17 Parlamentarischer Genehmigungsbeschluss, and `null` (55,401 affairs). There is no cantonal_initiative id.

## contributors[]
Fields: `type` (`person`|`group`), `fullname`, `firstname`, `lastname`, `position`, `role` (verbatim dict),
`role_harmonized` (dict, **no id**; use `.en`), `role_external_id`, `party` (verbatim dict, e.g. `{"de":"SP"}`),
`party_harmonized`, `person_id`/`group_id`. No separate faction field (faction not available -> `faction=None`).

`role_harmonized.en` seen: **Author**, Cosign, Speaker, Leading Department, Assigned Committee, Committee, Council Initial, Departement.
"Author" is lossy: it is also used for co-signatories whose verbatim `role` is e.g. "Mitunterzeichner(in)",
"Zweit-/Drittunterzeichner", "Cofirmatari", "Mitvorstoesser", "Miteinreichende"; first submitters read "Erstunterzeichner(in)",
"Urheber(-in)", "Presentata", "Auteur", "Hauptvorstoesser". Rule: Author + verbatim role matching the co-signer regex -> co_signatory (regex also covers "Cosignataire"/"Cofirmatario",
plain French/Italian translations of the evidenced Mitunterzeichner/Cofirmatari, not themselves seen in the data);
Author + empty or evidenced first-submitter verbatim (Erstunterzeichn*, Urheber*, Presentata, Auteur, Hauptvorstoess*) -> submitter;
any other verbatim role (e.g. "Beteiligung") is ambiguous: the person is kept with role `not_found` and flag `ambiguous_role:<verbatim>`.
"Council Initial" (a chamber) and "Departement" (Mitbeteiligtes Departement) are not mapped.
Group contributors "Leading Department" (Direktion / Federfuehrung) -> `executive_respondent`.

## events[]
Fields: `date` (ISO datetime), `position`, `title` (verbatim dict), `title_harmonized` (dict) + `title_harmonized_id`, `actor` (dict,
e.g. Regierung/Parlament), `last`. `title_harmonized_id` is `null` for many events (e.g. federal "Eingereicht"); those are skipped and
flagged, so `begin_date` supplies the `submitted` event.
Mapped ids: 1 Submitted, 6 Answered, 8 / 60 Dealt with by Parliament (-> debated), 26 Transferred, 27 Referred Postulate,
28 Transferred to committee (-> referred), 35 Rejected, 38 Done (Erledigt/Kenntnisnahme) (-> decided), 36 Depreciated
(-> written_off), 40 Zurueckgezogen (-> withdrawn).
Seen but NOT mapped (no clear state): 24 Agenda/Traktandiert, 29 "Motion: Reject" (Stellungnahme Regierungsrat), 32 "Motion: Transfer"
(proposals, not decisions), 47 Ready for the agenda, 67 Eingabe Vorstoss, 76 Beantwortung/Antrag, and all `null` ids.

## bodies
`GET /v1/bodies/`: `body_key`, `name` (dict), `type` in {country, canton, municipality, city}, `canton_key`, `country_key`, `lang`.
country -> federal only when `country_key == CHE` (the list also holds ~248 foreign countries, e.g. LIE); canton -> cantonal;
municipality and city -> municipal. Sample keys: CHE (country), ZH/GL/TI (canton), 261 Zuerich (city), 4551 Aadorf (municipality).
