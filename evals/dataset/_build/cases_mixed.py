"""Mixed-language cases (FI/SV, FI/EN). All names, identifiers and clinics are invented."""

# Document text is verbatim (en dashes, long lines are part of the test data).
# ruff: noqa: E501

from __future__ import annotations

from case import Case
from gold import (
    allergies_found,
    allergy,
    cond,
    daily,
    dosage,
    extraction,
    found,
    hetu,
    ident,
    med,
    name,
    nka_statement,
    patient,
    reaction,
)

# ---------------------------------------------------------------------------------------------
# mx01: bilingual FI/SV discharge summary with a Swedish consultation paragraph
# ---------------------------------------------------------------------------------------------

H01 = hetu("1944-02-29", 951)
MX01_DOC = f"""EPIKRIISI / EPIKRIS
Kuvitteelan keskussairaala, kirurgian osasto K4 / Kirurgiska avdelningen K4
SYNTEETTINEN TESTIASIAKIRJA - SYNTETISKT TESTDOKUMENT

Potilas / Patient: Kokkonen-Prov, Elsa Maria
Hetu / Personbeteckning: {H01}
Hoitojakso / Vårdtid: 26.9.-30.9.2026

DIAGNOOSIT / DIAGNOSER
K80.2 Sappikivitauti / Gallsten
K57.3 Paksusuolen divertikuloosi, todettu 2019

ALLERGIAT / ALLERGIER
Ei tiedossa olevia lääkeaineallergioita / Inga kända läkemedelsallergier. Laktoosi-intoleranssi.

HOIDON KULKU
Potilas tuli päivystykseen oikean kylkikaaren alaisen kivun vuoksi. UÄ:ssä sappikiviä, ei kolekystiittiä.
Laparoskooppinen kolekystektomia 27.9.2026, toipuminen hyvä.

Konsultation, internmedicin (på svenska): Patienten har känd hypertoni sedan 2012 och förmaksflimmer.
Rekommenderar fortsatt Eliquis 5 mg 1 x 2. Kaliumvärdet lågt, Kaleorid 750 mg 1 x 2 i två veckor.

KOTILÄÄKITYS / HEMMEDICINERING
Eliquis 5 mg tabl 1 x 2
Amlodipin 5 mg tabl 1 x 1
Kaleorid 750 mg depottabl 1 x 2 kahden viikon ajan
Panacod 500/30 mg tabl 1-2 tarv. kipuun, max 6/vrk, 3 vrk ajan
"""

MX01 = Case(
    case_id="mx01_discharge_fi_sv_txt",
    language="fi+sv",
    fmt="txt",
    doc_type="discharge_summary",
    features=(
        "mixed_language",
        "printed_icd10",
        "duplicated_medication",
        "as_needed_dosing",
        "abbreviations",
        "intolerance",
        "procedure_distractor",
        "partial_dates",
        "caps_headings",
        "hetu_without_birth_date",
    ),
    notes=(
        "Bilingual headings; Swedish consultation paragraph. The same 'no known drug allergies' "
        "statement is given in Finnish and Swedish (gold keeps one, the first). Eliquis and "
        "Kaleorid appear in the consultation and the list (gold quotes the list). The "
        "cholecystectomy is a procedure. 'Paksusuolen' only locates the diverticulosis, so it "
        "goes to body_site_text."
    ),
    document=MX01_DOC,
    gold=extraction(
        "fi",
        patient(
            names=[
                name(
                    "Kokkonen-Prov, Elsa Maria",
                    family="Kokkonen-Prov",
                    given=["Elsa", "Maria"],
                )
            ],
            identifiers=[
                ident(
                    f"Hetu / Personbeteckning: {H01}",
                    H01,
                    "Hetu / Personbeteckning",
                )
            ],
        ),
        allergies_found(
            [
                allergy(
                    "Laktoosi-intoleranssi",
                    "Laktoosi",
                    type="intolerance",
                    category="food",
                )
            ],
            [nka_statement("Ei tiedossa olevia lääkeaineallergioita", "medication")],
        ),
        found(
            med(
                "Eliquis 5 mg tabl 1 x 2",
                "Eliquis",
                strength="5 mg",
                form="tabl",
                dose=daily("1 x 2", "1", "tabl", "2"),
            ),
            med(
                "Amlodipin 5 mg tabl 1 x 1",
                "Amlodipin",
                strength="5 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Kaleorid 750 mg depottabl 1 x 2 kahden viikon ajan",
                "Kaleorid",
                strength="750 mg",
                form="depottabl",
                dose=daily("1 x 2 kahden viikon ajan", "1", "depottabl", "2"),
            ),
            med(
                "Panacod 500/30 mg tabl 1-2 tarv. kipuun, max 6/vrk, 3 vrk ajan",
                "Panacod",
                strength="500/30 mg",
                form="tabl",
                dose=dosage("1-2 tarv. kipuun, max 6/vrk, 3 vrk ajan", unit="tabl", prn=True),
                reason="kipuun",
            ),
        ),
        found(
            cond("K80.2 Sappikivitauti / Gallsten", "Sappikivitauti", code="K80.2"),
            cond(
                "K57.3 Paksusuolen divertikuloosi, todettu 2019",
                "divertikuloosi",
                code="K57.3",
                body_site="Paksusuolen",
                verification="confirmed",
                onset="2019",
            ),
            cond("känd hypertoni sedan 2012", "hypertoni", onset="2012"),
            cond("förmaksflimmer", "förmaksflimmer"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# mx02: Finnish referral PDF quoting an English GP letter
# ---------------------------------------------------------------------------------------------

H02 = hetu("1969-08-14", 988)
MX02_PAGES = [
    [
        "# LÄHETE - Gastroenterologian poliklinikka",
        "Kuvitteelan terveysasema | SYNTEETTINEN TESTIASIAKIRJA - EI OIKEA POTILAS",
        "Potilas: Testinen-Smith, Johanna",
        f"Henkilötunnus: {H02}",
        "",
        "Lähetteen syy: Ylävatsakivut ja painonlasku 4 kg 3 kk aikana. Gastroskopia?",
        "",
        "Potilas muuttanut Suomeen Iso-Britanniasta 2025. Ote englanninkielisestä",
        "potilaskertomuksesta (GP letter, 2025):",
        '"PMH: Coeliac disease (diagnosed 2008), on gluten-free diet.',
        "Iron deficiency anaemia 2023 - resolved.",
        "Allergies: Penicillin (rash). No other known allergies.",
        'Medication: Ferrous sulphate 200 mg OD - stopped 11/2023. Omeprazole 20 mg OD."',
        "",
        "Nykyinen lääkitys: Omeprazol 20 mg 1x1 aamulla. Ei muuta säännöllistä lääkitystä.",
        "Sukuanamneesi: äidillä paksusuolisyöpä 60-vuotiaana.",
        "",
        "Lääkäri: Testi Yleislääkäri",
    ]
]

MX02 = Case(
    case_id="mx02_referral_fi_en_pdf",
    language="fi+en",
    fmt="pdf",
    doc_type="referral_letter",
    features=(
        "mixed_language",
        "resolved_condition",
        "stopped_medication",
        "duplicated_medication",
        "family_history_distractor",
        "partial_dates",
        "abbreviations",
        "hetu_without_birth_date",
        "allergy_reactions",
    ),
    notes=(
        "Finnish referral quoting an English GP letter. Omeprazole appears in both (gold quotes "
        "the current Finnish line). Presenting symptoms without a diagnosis (upper abdominal "
        "pain, weight loss) count as problems. 'No other known allergies' and 'Ei muuta "
        "säännöllistä lääkitystä' only confirm the lists."
    ),
    document=MX02_PAGES,
    gold=extraction(
        "fi",
        patient(
            names=[name("Testinen-Smith, Johanna", family="Testinen-Smith", given=["Johanna"])],
            identifiers=[ident(f"Henkilötunnus: {H02}", H02, "Henkilötunnus")],
        ),
        allergies_found(
            [
                allergy(
                    "Penicillin (rash)",
                    "Penicillin",
                    category="medication",
                    reactions=[reaction("rash")],
                )
            ]
        ),
        found(
            med(
                "Ferrous sulphate 200 mg OD - stopped 11/2023",
                "Ferrous sulphate",
                strength="200 mg",
                dose=dosage("OD", freq="1", period="1", period_unit="d"),
                status="stopped",
                end="2023-11",
            ),
            med(
                "Omeprazol 20 mg 1x1 aamulla",
                "Omeprazol",
                strength="20 mg",
                dose=daily("1x1 aamulla", "1", "", "1"),
            ),
        ),
        found(
            cond("Ylävatsakivut", "Ylävatsakivut", confidence="medium"),
            cond(
                "painonlasku 4 kg 3 kk aikana",
                "painonlasku",
                note="4 kg 3 kk aikana",
                confidence="medium",
            ),
            cond(
                "Coeliac disease (diagnosed 2008)",
                "Coeliac disease",
                verification="confirmed",
                onset="2008",
            ),
            cond(
                "Iron deficiency anaemia 2023 - resolved.",
                "Iron deficiency anaemia",
                status="resolved",
                onset="2023",
            ),
        ),
    ),
)

CASES = [MX01, MX02]
