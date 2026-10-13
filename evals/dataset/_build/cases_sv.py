"""Swedish (Finland-Swedish) cases. All names, identifiers, clinics and people are invented."""

# Document text is verbatim (en dashes, long lines are part of the test data).
# ruff: noqa: RUF001

from __future__ import annotations

from case import Case
from cases_fi import csv_segment
from gold import (
    NO_INFO,
    allergies_found,
    allergy,
    birth,
    cond,
    daily,
    dosage,
    extraction,
    found,
    gender,
    hetu,
    ident,
    med,
    name,
    nka_statement,
    no_known_allergies,
    none_known,
    patient,
    reaction,
)

# ---------------------------------------------------------------------------------------------
# sv01: discharge summary, plaintext, NKDA + peanut allergy, ICD-10, stopped warfarin
# ---------------------------------------------------------------------------------------------

H01 = hetu("1946-08-12", 948)
SV01_DOC = f"""VASA TESTSJUKHUS (fiktivt) – Medicinska avdelningen M2
SYNTETISKT TESTDOKUMENT – INTE EN VERKLIG PATIENT

EPIKRIS

Patient: Provsson, Karl-Erik
Personbeteckning: {H01}
Född: 12.08.1946
Kön: man
Vårdtid: 15.09.2026–19.09.2026

ORSAK TILL INLÄGGNING
Bröstsmärta och andnöd. Förmaksflimmer med snabb kammarfrekvens, RR 158/96.

TIDIGARE SJUKDOMAR
Lunginflammation 2021, utläkt.
Höftprotes vänster 2018.

DIAGNOSER
I48.0 Paroxysmalt förmaksflimmer
I10 Essentiell hypertoni
E78.0 Hyperkolesterolemi

ALLERGIER
Inga kända läkemedelsallergier. Jordnötsallergi (anafylaxi 2008), bär adrenalinpenna.

BEHANDLING
Warfarin utsattes och Eliquis insattes, se läkemedelslistan. Metoprolol dosen höjdes.

LÄKEMEDEL VID UTSKRIVNING
Eliquis 5 mg 1 tabl x 2, insatt 17.09.2026
Metoprolol depot 100 mg 1 x 1 morgon
Enalapril 10 mg 1 x 1
Atorvastatin 40 mg 1 x 1 till kvällen
Alvedon 500 mg 1–2 tabl vid behov, högst 6 tabl/dygn
EpiPen 0,3 mg autoinjektor vid anafylaxi
Warfarin (Marevan) 3 mg – UTSATT 17.09.2026, ersatt med Eliquis

Uppföljning: Kontroll hos hälsovårdscentralens läkare om 2 veckor.
"""

SV01 = Case(
    case_id="sv01_discharge_medicine_txt",
    language="sv",
    fmt="txt",
    doc_type="discharge_summary",
    features=(
        "nkda_plus_food_allergy",
        "printed_icd10",
        "resolved_condition",
        "duplicated_medication",
        "stopped_medication",
        "as_needed_dosing",
        "abbreviations",
        "procedure_distractor",
        "caps_headings",
        "partial_dates",
        "decimal_comma",
        "gender_stated",
        "birth_date_stated",
        "allergy_reactions",
    ),
    notes=(
        "Finland-Swedish discharge summary. Warfarin/Eliquis/Metoprolol appear in the narrative "
        "and the list (reported once, from the list). Hip prosthesis is a procedure. EpiPen "
        "'vid anafylaxi' is used only on a trigger: as_needed true."
    ),
    document=SV01_DOC,
    gold=extraction(
        "sv",
        patient(
            names=[name("Provsson, Karl-Erik", family="Provsson", given=["Karl-Erik"])],
            birth_date=birth("Född: 12.08.1946", "1946-08-12"),
            gender=gender("Kön: man", "male"),
            identifiers=[ident(f"Personbeteckning: {H01}", H01, "Personbeteckning")],
        ),
        allergies_found(
            [
                allergy(
                    "Jordnötsallergi (anafylaxi 2008)",
                    "Jordnöt",
                    type="allergy",
                    category="food",
                    onset="2008",
                    reactions=[reaction("anafylaxi")],
                )
            ],
            [nka_statement("Inga kända läkemedelsallergier", "medication")],
        ),
        found(
            med(
                "Eliquis 5 mg 1 tabl x 2, insatt 17.09.2026",
                "Eliquis",
                strength="5 mg",
                dose=daily("1 tabl x 2", "1", "tabl", "2"),
                start="2026-09-17",
            ),
            med(
                "Metoprolol depot 100 mg 1 x 1 morgon",
                "Metoprolol",
                strength="100 mg",
                form="depot",
                dose=daily("1 x 1 morgon", "1", "", "1"),
            ),
            med(
                "Enalapril 10 mg 1 x 1",
                "Enalapril",
                strength="10 mg",
                dose=daily("1 x 1", "1", "", "1"),
            ),
            med(
                "Atorvastatin 40 mg 1 x 1 till kvällen",
                "Atorvastatin",
                strength="40 mg",
                dose=daily("1 x 1 till kvällen", "1", "", "1"),
            ),
            med(
                "Alvedon 500 mg 1–2 tabl vid behov, högst 6 tabl/dygn",
                "Alvedon",
                strength="500 mg",
                dose=dosage("1–2 tabl vid behov, högst 6 tabl/dygn", unit="tabl", prn=True),
            ),
            med(
                "EpiPen 0,3 mg autoinjektor vid anafylaxi",
                "EpiPen",
                strength="0,3 mg",
                form="autoinjektor",
                dose=dosage("vid anafylaxi", prn=True),
                reason="anafylaxi",
            ),
            med(
                "Warfarin (Marevan) 3 mg – UTSATT 17.09.2026, ersatt med Eliquis",
                "Warfarin (Marevan)",
                strength="3 mg",
                status="stopped",
                end="2026-09-17",
                note="ersatt med Eliquis",
            ),
        ),
        found(
            cond(
                "Lunginflammation 2021, utläkt.",
                "Lunginflammation",
                status="resolved",
                onset="2021",
            ),
            cond("I48.0 Paroxysmalt förmaksflimmer", "Paroxysmalt förmaksflimmer", code="I48.0"),
            cond("I10 Essentiell hypertoni", "Essentiell hypertoni", code="I10"),
            cond("E78.0 Hyperkolesterolemi", "Hyperkolesterolemi", code="E78.0"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# sv02: referral, 2-page PDF, "Inga kända allergier", family history, suspected diagnosis
# ---------------------------------------------------------------------------------------------

H02 = hetu("1952-03-03", 919)
SV02_PAGES = [
    [
        "# REMISS - Neurologiska polikliniken",
        "Testby hälsocentral (fiktiv) | SYNTETISKT TESTDOKUMENT",
        "Datum: 24.09.2026",
        "Patient: Birgitta Testström",
        f"Personbeteckning: {H02}",
        "",
        "# Frågeställning",
        "74-årig kvinna med tilltagande skakningar i höger hand sedan våren 2025,",
        "långsamma rörelser och små steg. Misstänkt Parkinsons sjukdom, ber om bedömning.",
        "",
        "# Anamnes",
        "Hypertoni sedan 2010, välbehandlad.",
        "Depression 2015-2016, utläkt.",
        "Mor har haft bröstcancer, morfar hade Parkinsons sjukdom.",
        "",
        "# Allergier",
        "Inga kända allergier.",
        "",
        "(fortsättning på sida 2)",
    ],
    [
        "# Aktuella läkemedel",
        "Enalapril 10 mg 1x1",
        "Alvedon 500 mg 1-2 tabl vid behov",
        "D-vitamin 50 mikrog 1 kapsel dagligen",
        "",
        "# Status",
        "RR 136/82. Vilotremor höger hand, rigiditet höger arm. Övrigt neurologiskt status u.a.",
        "",
        "Med vänlig hälsning",
        "Test Läkare, specialist i allmänmedicin",
    ],
]

SV02 = Case(
    case_id="sv02_referral_neuro_pdf",
    language="sv",
    fmt="pdf",
    doc_type="referral_letter",
    features=(
        "multi_page_pdf",
        "none_known_allergies",
        "family_history_distractor",
        "suspected_condition",
        "resolved_condition",
        "partial_dates",
        "as_needed_dosing",
        "abbreviations",
        "gender_stated",
        "hetu_without_birth_date",
    ),
    notes=(
        "Two-page referral PDF; medications are on page 2. The grandfather's Parkinson's disease "
        "and the mother's breast cancer are family history. Tremor is covered by the suspected "
        "diagnosis and not listed separately."
    ),
    document=SV02_PAGES,
    gold=extraction(
        "sv",
        patient(
            names=[name("Birgitta Testström", family="Testström", given=["Birgitta"])],
            gender=gender("74-årig kvinna", "female"),
            identifiers=[ident(f"Personbeteckning: {H02}", H02, "Personbeteckning")],
        ),
        no_known_allergies("Inga kända allergier.", "all"),
        found(
            med(
                "Enalapril 10 mg 1x1",
                "Enalapril",
                strength="10 mg",
                dose=daily("1x1", "1", "", "1"),
            ),
            med(
                "Alvedon 500 mg 1-2 tabl vid behov",
                "Alvedon",
                strength="500 mg",
                dose=dosage("1-2 tabl vid behov", unit="tabl", prn=True),
            ),
            med(
                "D-vitamin 50 mikrog 1 kapsel dagligen",
                "D-vitamin",
                strength="50 mikrog",
                dose=daily("1 kapsel dagligen", "1", "kapsel", "1"),
            ),
        ),
        found(
            cond(
                "Misstänkt Parkinsons sjukdom",
                "Parkinsons sjukdom",
                verification="provisional",
            ),
            cond(
                "Hypertoni sedan 2010, välbehandlad.",
                "Hypertoni",
                onset="2010",
                note="välbehandlad",
            ),
            cond(
                "Depression 2015-2016, utläkt.",
                "Depression",
                status="resolved",
                onset="2015",
                abatement="2016",
            ),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# sv03: medication list, CSV with ',' and quoted decimal commas; stopped + paused
# ---------------------------------------------------------------------------------------------

SV03_HEADERS = ["Läkemedel", "Styrka", "Form", "Dosering", "Ändamål", "Status", "Kommentar"]
SV03_ROWS = [
    ["Levaxin", "0,1 mg", "tablett", "1 x 1 på morgonen", "hypotyreos", "Aktuell", ""],
    ["Losartan", "50 mg", "tablett", "1 x 1", "blodtryck", "Aktuell", ""],
    ["Metformin", "500 mg", "tablett", "1 x 2 (morgon, kväll)", "diabetes", "Aktuell", ""],
    ["Ipren", "400 mg", "tablett", "1 vb", "smärta", "Utsatt", "utsatt 03/2026 pga magbesvär"],
    ["Omeprazol", "20 mg", "kapsel", "1 x 1", "magskydd", "Uppehåll",
     "uppehåll under utredning"],
    ["Nitroglycerin", "0,25 mg", "resoriblett", "1 vb vid bröstsmärta", "kärlkramp", "Aktuell",
     ""],
]  # fmt: skip


def _csv_cell(cell: str) -> str:
    return f'"{cell}"' if "," in cell else cell


SV03_DOC = "\n".join(",".join(_csv_cell(c) for c in r) for r in [SV03_HEADERS, *SV03_ROWS])
SV03_DOC += "\n"


def _sv03(i: int) -> str:
    return csv_segment(SV03_HEADERS, SV03_ROWS[i])


SV03 = Case(
    case_id="sv03_medlist_comma_csv",
    language="sv",
    fmt="csv",
    doc_type="medication_list",
    features=(
        "decimal_comma",
        "stopped_medication",
        "paused_medication",
        "as_needed_dosing",
        "abbreviations",
        "indication_not_problem",
        "section_no_information",
        "partial_dates",
    ),
    notes=(
        "Comma-separated medication list with quoted cells containing commas. No patient data. "
        "Indications (hypotyreos, diabetes, kärlkramp) stay in reason_text; problems and "
        "allergies are no_information."
    ),
    document=SV03_DOC,
    gold=extraction(
        "sv",
        patient(),
        NO_INFO,
        found(
            med(
                _sv03(0),
                "Levaxin",
                strength="0,1 mg",
                form="tablett",
                dose=daily("1 x 1 på morgonen", "1", "tablett", "1"),
                reason="hypotyreos",
            ),
            med(
                _sv03(1),
                "Losartan",
                strength="50 mg",
                form="tablett",
                dose=daily("1 x 1", "1", "tablett", "1"),
                reason="blodtryck",
            ),
            med(
                _sv03(2),
                "Metformin",
                strength="500 mg",
                form="tablett",
                dose=daily("1 x 2 (morgon, kväll)", "1", "tablett", "2"),
                reason="diabetes",
            ),
            med(
                _sv03(3),
                "Ipren",
                strength="400 mg",
                form="tablett",
                dose=dosage("1 vb", "1", "tablett", prn=True),
                status="stopped",
                end="2026-03",
                reason="smärta",
                note="utsatt 03/2026 pga magbesvär",
            ),
            med(
                _sv03(4),
                "Omeprazol",
                strength="20 mg",
                form="kapsel",
                dose=daily("1 x 1", "1", "kapsel", "1"),
                status="on_hold",
                reason="magskydd",
                note="uppehåll under utredning",
            ),
            med(
                _sv03(5),
                "Nitroglycerin",
                strength="0,25 mg",
                form="resoriblett",
                dose=dosage("1 vb vid bröstsmärta", "1", "resoriblett", prn=True),
                reason="kärlkramp",
            ),
        ),
        NO_INFO,
    ),
)

# ---------------------------------------------------------------------------------------------
# sv04: outpatient note as JSON (sections with headings), no regular medication
# ---------------------------------------------------------------------------------------------

H04 = hetu("1990-06-15", 961)
SV04_DOC = {
    "journalanteckning": {
        "datum": "2026-09-22",
        "enhet": "Testby hälsocentral (fiktiv enhet)",
        "yrkesroll": "Läkare",
        "patient": {"namn": "Exempelqvist, Linnea", "personbeteckning": H04, "kön": "kvinna"},
        "sektioner": [
            {"rubrik": "Kontaktorsak", "text": "Huvudvärk, återkommande, ca 3 attacker/månad."},
            {
                "rubrik": "Diagnoser",
                "rader": [
                    "Migrän utan aura (G43.0)",
                    "Järnbristanemi 2023, behandlad och utläkt",
                ],
            },
            {"rubrik": "Allergier", "text": "Björkpollenallergi med rinokonjunktivit varje vår."},
            {"rubrik": "Läkemedel", "text": "Inga regelbundna läkemedel."},
            {
                "rubrik": "Bedömning",
                "text": "Migrän utan aura. Rekommenderar huvudvärksdagbok. Ny kontakt vid behov.",
            },
        ],
        "syntetiska_data": True,
    }
}

SV04 = Case(
    case_id="sv04_outpatient_sections_json",
    language="sv",
    fmt="json",
    doc_type="outpatient_note",
    features=(
        "no_regular_medication",
        "printed_icd10",
        "resolved_condition",
        "partial_dates",
        "gender_stated",
        "allergy_reactions",
        "hetu_without_birth_date",
    ),
    notes=(
        "JSON note made of headed text sections. 'Inga regelbundna läkemedel' -> medications "
        "none_known. Migraine also appears in the assessment (reported once, with its code)."
    ),
    document=SV04_DOC,
    gold=extraction(
        "sv",
        patient(
            names=[name("Exempelqvist, Linnea", family="Exempelqvist", given=["Linnea"])],
            gender=gender("kön: kvinna", "female"),
            identifiers=[ident(f"personbeteckning: {H04}", H04, "personbeteckning")],
        ),
        allergies_found(
            [
                allergy(
                    "Björkpollenallergi med rinokonjunktivit",
                    "Björkpollen",
                    type="allergy",
                    category="environment",
                    reactions=[reaction("rinokonjunktivit")],
                )
            ]
        ),
        none_known("Inga regelbundna läkemedel."),
        found(
            cond("Migrän utan aura (G43.0)", "Migrän utan aura", code="G43.0"),
            cond(
                "Järnbristanemi 2023, behandlad och utläkt",
                "Järnbristanemi",
                status="resolved",
                onset="2023",
            ),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# sv05: lab report as JSON, nothing for the three sections
# ---------------------------------------------------------------------------------------------

H05 = hetu("1971-11-02", 974)
SV05_DOC = {
    "provsvar": {
        "laboratorium": "Testlab Österbotten (fiktivt)",
        "remitterande_enhet": "Testby hälsocentral",
        "patient": {"efternamn": "Provberg", "fornamn": "Nils Olof", "id": H05},
        "provtagning": "2026-09-30T07:40",
        "analyser": [
            {"kod": "B-Hb", "resultat": "151", "enhet": "g/l", "referens": "134-167"},
            {"kod": "P-ALAT", "resultat": "68", "enhet": "U/l", "referens": "< 50", "flagga": "H"},
            {"kod": "P-GT", "resultat": "112", "enhet": "U/l", "referens": "< 80", "flagga": "H"},
            {
                "kod": "fP-Trigly",
                "resultat": "2,4",
                "enhet": "mmol/l",
                "referens": "< 1,7",
                "flagga": "H",
            },
            {"kod": "P-CRP", "resultat": "< 3", "enhet": "mg/l", "referens": "< 3"},
        ],
        "kommentar": "Förhöjda leverenzymer, kontroll om 4 veckor rekommenderas.",
    }
}

SV05 = Case(
    case_id="sv05_lab_report_json",
    language="sv",
    fmt="json",
    doc_type="lab_report",
    features=(
        "lab_report_all_no_information",
        "section_no_information",
        "decimal_comma",
        "multi_segment_quote",
        "hetu_without_birth_date",
    ),
    notes=(
        "Lab system JSON. Raised liver enzymes are findings, not diagnoses: all three sections "
        "are no_information. The name is split over two leaves (multi-segment quote)."
    ),
    document=SV05_DOC,
    gold=extraction(
        "sv",
        patient(
            names=[
                name(
                    "Provberg\nprovsvar.patient.fornamn: Nils Olof",
                    text="Provberg Nils Olof",
                    family="Provberg",
                    given=["Nils", "Olof"],
                )
            ],
            identifiers=[ident(f"id: {H05}", H05, "id", confidence="medium")],
        ),
        NO_INFO,
        NO_INFO,
        NO_INFO,
    ),
)

# ---------------------------------------------------------------------------------------------
# sv06: e-prescription summary, PDF, NKDA only, indications
# ---------------------------------------------------------------------------------------------

H06 = hetu("1999-04-21", 933)
SV06_AMOX = [
    "Amoxicillin Orion 500 mg kapsel, 21 st",
    "Dosering: 1 kapsel 3 gånger dagligen i 7 dagar",
    "Ändamål: mot öroninflammation",
]
SV06_IBU = [
    "Ibuprofen 400 mg tablett, 30 st",
    "Dosering: 1 tablett 1-3 gånger dagligen vid behov mot smärta",
]
SV06_PAGES = [
    [
        "# E-RECEPT - SAMMANFATTNING FÖR PATIENTEN",
        "SYNTETISKT TESTDOKUMENT - INTE ETT GILTIGT RECEPT",
        "Patient: Oskar Testlund",
        f"Personbeteckning: {H06}",
        "Förskrivningsdatum: 01.10.2026",
        "Förskrivare: Test Läkare, Testby hälsocentral (fiktiv)",
        "Allergiuppgifter: Inga kända läkemedelsallergier",
        "",
        "# Förskrivet läkemedel 1",
        *SV06_AMOX,
        "",
        "# Förskrivet läkemedel 2",
        *SV06_IBU,
        "",
        "Receptet är giltigt i 2 år. Expedieras på apotek.",
    ]
]

SV06 = Case(
    case_id="sv06_prescription_pdf",
    language="sv",
    fmt="pdf",
    doc_type="prescription",
    features=(
        "none_known_allergies",
        "as_needed_dosing",
        "indication_not_problem",
        "section_no_information",
        "hetu_without_birth_date",
    ),
    notes=(
        "Prescription summary. 'Inga kända läkemedelsallergier' alone -> allergies none_known "
        "with scope medication. Otitis is only an indication: problems no_information. "
        "Medication quotes span the product, dosage and indication lines."
    ),
    document=SV06_PAGES,
    gold=extraction(
        "sv",
        patient(
            names=[name("Oskar Testlund", family="Testlund", given=["Oskar"])],
            identifiers=[ident(f"Personbeteckning: {H06}", H06, "Personbeteckning")],
        ),
        no_known_allergies("Inga kända läkemedelsallergier", "medication"),
        found(
            med(
                "\n".join(SV06_AMOX),
                "Amoxicillin Orion",
                strength="500 mg",
                form="kapsel",
                dose=daily("1 kapsel 3 gånger dagligen i 7 dagar", "1", "kapsel", "3"),
                reason="öroninflammation",
            ),
            med(
                "\n".join(SV06_IBU),
                "Ibuprofen",
                strength="400 mg",
                form="tablett",
                dose=dosage(
                    "1 tablett 1-3 gånger dagligen vid behov mot smärta",
                    "1",
                    "tablett",
                    prn=True,
                ),
                reason="smärta",
            ),
        ),
        NO_INFO,
    ),
)

CASES = [SV01, SV02, SV03, SV04, SV05, SV06]
