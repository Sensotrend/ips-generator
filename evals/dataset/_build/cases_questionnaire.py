"""Cases written to be good candidates for pre-filling the physiotherapy low-back questionnaire and
the maternity clinic pre-visit questionnaire (github.com/Sensotrend/hackathon-questionnaires).

All names, identifiers, clinics and people are invented (synthetic); nothing is derived from the
LUVN hackathon data. Each document has what the questionnaire's pre-population looks for:

* physiotherapy: several long-term diagnoses that fall under the questionnaire's illness
  checklist (ICD-10 printed next to each), a low-back pain diagnosis, active medication and an
  explicit allergy statement, plus height, weight and smoking in the text;
* maternity: chronic illnesses from the checklist (diabetes, thyroid, asthma, hypertension,
  epilepsy, bowel disease, heart defect, thrombosis), prescription medicines and supplements
  (folic acid, vitamin D, calcium, B12, multivitamin), allergies, plus the pregnancy history,
  last menstrual period, height, weight, vaccinations and contact person in the text.

The gold covers only the three IPS sections and the patient (the extraction schema). The facts
the questionnaires also use but the schema cannot hold (height, weight, smoking, pregnancy history,
vaccinations, contact person) are in the documents as realistic context, so a pipeline that later
extracts them can use these cases too. The same goes for the other IPS sections, spread over the
cases: vital signs, results, vaccinations with dates, procedures, devices, advance directive,
alerts, functional status, patient's own words and plan of care. Resolved past conditions
('parantunut') are problems and are in the gold. A current pregnancy written as a diagnosis line (Z32.1) is a
problem; the pregnancy history and dates in the narrative are not.
"""

# Document text is verbatim (long lines are part of the test data).
# ruff: noqa: RUF001, E501

from __future__ import annotations

from dataclasses import replace
from typing import Any

from case import Case
from gold import (
    allergies_found,
    allergy,
    birth,
    cond,
    contact,
    daily,
    device,
    document_date,
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
    patient,
    pregnancy_fact,
    procedure,
    reaction,
    result,
    social,
    vaccine,
    vital,
)

PHYSIO = "physio_questionnaire_candidate"
MATERNITY = "maternity_questionnaire_candidate"
NON_SCHEMA = "non_schema_facts"

# ---------------------------------------------------------------------------------------------
# fi13: physiotherapy referral, GP, hypertension + dyslipidaemia + type 2 diabetes + reflux
# ---------------------------------------------------------------------------------------------

H13 = hetu("1968-02-12", 917)
FI13_DOC = f"""KUVITTEELAN TERVEYSASEMA / Vastaanotto
SYNTEETTINEN TESTIASIAKIRJA - EI OIKEA POTILAS

LÄHETE FYSIOTERAPIAAN

Potilas: KORHONEN-TESTI, Matti Olavi
Henkilötunnus: {H13}
Syntymäaika: 12.02.1968
Sukupuoli: mies
Lähetepäivä: 06.10.2026

LÄHETTEEN SYY
Alaselkäkipu on alkanut noin 6 viikkoa sitten raskaan kuorman nostamisen jälkeen. Kipu tuntuu alaselässä eikä säteile jalkoihin. Neurologinen status on normaali. Pyydän fysioterapeutin arviota ja harjoitusohjelmaa.

TAUSTA
Pituus 178 cm, paino 94 kg. Ei tupakoi. Alkoholia käyttää vähän. Työ: varastotyöntekijä, työkyky osittain alentunut.

MITTAUKSET JA TULOKSET
Verenpaine 138/84 mmHg, pulssi 72/min, painoindeksi 29,7 (06.10.2026).
HbA1c 52 mmol/mol, P-Krea 78 µmol/l, LDL-kolesteroli 2,9 mmol/l (24.09.2026).

TOIMINTAKYKY
Liikkuu ja asioi itsenäisesti. Nostaminen, pitkä seisominen ja yli 30 minuutin autolla ajo ovat vaikeita kivun vuoksi.

DIAGNOOSIT
M54.5 Alaselkäkipu, alkanut elokuussa 2026
I10 Verenpainetauti, todettu 2016
E78.0 Hyperkolesterolemia
E11.9 Tyypin 2 diabetes, todettu 2020
K21.9 Refluksitauti
E66.9 Ylipaino
J18.9 Keuhkokuume 2019, parantunut

LÄÄKITYS
- Amlodipiini 5 mg tabl 1 x 1 (ATC C08CA01)
- Atorvastatiini 20 mg tabl 1 x 1 iltaisin
- Metformiini 1 g tabl 1 x 2
- Pantopratsoli 20 mg tabl 1 x 1 aamulla
- Ibuprofeeni 400 mg tabl 1 tarv., max 3 x vrk

ALLERGIAT
Ei tiedossa olevia lääkeaineallergioita.

SUUNNITELMA
Fysioterapiajakso 6 käyntiä 8 viikon aikana. Tavoite: pystyy nostamaan työssä kuormaa ilman kipua 3 kuukauden kuluessa. Lääkärin kontrolli 8 viikon kuluttua.

Testi Lääkäri, yleislääketieteen erikoislääkäri
"""

FI13 = Case(
    case_id="fi13_referral_physio_lbp_txt",
    language="fi",
    fmt="txt",
    doc_type="referral_letter",
    features=(
        PHYSIO,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "resolved_condition",
        "as_needed_dosing",
        "partial_dates",
        "abbreviations",
        "decimal_comma",
        "none_known_allergies",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "GP referral to physiotherapy for low back pain. Also carries vital signs, lab results, "
        "functional status and a plan of care (context only), and a resolved pneumonia (past "
        "problem, 'parantunut'). Four diagnoses fall under the physiotherapy "
        "questionnaire's illness checklist (I10, E78.0, E11.9, K21.9) and E66.9 under overweight; "
        "M54.5 gives the pain duration. Height, weight and smoking are context only (not in the "
        "schema). 'Ei tiedossa olevia lääkeaineallergioita' is a drug-scoped none-known statement."
    ),
    document=FI13_DOC,
    gold=extraction(
        "fi",
        patient(
            names=[
                name("KORHONEN-TESTI, Matti Olavi", family="KORHONEN-TESTI", given=["Matti", "Olavi"])
            ],
            birth_date=birth("Syntymäaika: 12.02.1968", "1968-02-12"),
            gender=gender("Sukupuoli: mies", "male"),
            identifiers=[ident(f"Henkilötunnus: {H13}", H13, "Henkilötunnus")],
        ),
        no_known_allergies("Ei tiedossa olevia lääkeaineallergioita.", "medication"),
        found(
            med(
                "Amlodipiini 5 mg tabl 1 x 1 (ATC C08CA01)",
                "Amlodipiini",
                code="C08CA01",
                code_system="ATC",
                strength="5 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Atorvastatiini 20 mg tabl 1 x 1 iltaisin",
                "Atorvastatiini",
                strength="20 mg",
                form="tabl",
                dose=daily("1 x 1 iltaisin", "1", "tabl", "1"),
            ),
            med(
                "Metformiini 1 g tabl 1 x 2",
                "Metformiini",
                strength="1 g",
                form="tabl",
                dose=daily("1 x 2", "1", "tabl", "2"),
            ),
            med(
                "Pantopratsoli 20 mg tabl 1 x 1 aamulla",
                "Pantopratsoli",
                strength="20 mg",
                form="tabl",
                dose=daily("1 x 1 aamulla", "1", "tabl", "1"),
            ),
            med(
                "Ibuprofeeni 400 mg tabl 1 tarv., max 3 x vrk",
                "Ibuprofeeni",
                strength="400 mg",
                form="tabl",
                dose=dosage("1 tarv., max 3 x vrk", dose="1", unit="tabl", prn=True),
            ),
        ),
        found(
            cond(
                "M54.5 Alaselkäkipu, alkanut elokuussa 2026",
                "Alaselkäkipu",
                code="M54.5",
                onset="2026-08",
            ),
            cond(
                "I10 Verenpainetauti, todettu 2016",
                "Verenpainetauti",
                code="I10",
                verification="confirmed",
                onset="2016",
            ),
            cond("E78.0 Hyperkolesterolemia", "Hyperkolesterolemia", code="E78.0"),
            cond(
                "E11.9 Tyypin 2 diabetes, todettu 2020",
                "Tyypin 2 diabetes",
                code="E11.9",
                verification="confirmed",
                onset="2020",
            ),
            cond("K21.9 Refluksitauti", "Refluksitauti", code="K21.9"),
            cond("E66.9 Ylipaino", "Ylipaino", code="E66.9"),
            cond(
                "J18.9 Keuhkokuume 2019, parantunut",
                "Keuhkokuume",
                code="J18.9",
                status="resolved",
                onset="2019",
            ),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# fi14: physiotherapy outpatient note, osteoporosis + depression + hypothyroidism, codeine intolerance
# ---------------------------------------------------------------------------------------------

H14 = hetu("1977-07-21", 923)
FI14_DOC = f"""KUVITTEELAN TERVEYSASEMA / Lääkärin vastaanotto
SYNTEETTINEN TESTIASIAKIRJA - EI OIKEA POTILAS

LÄÄKÄRIN KIRJAUS

Potilas: LEHTINEN-TESTI, Sari Marjatta
Henkilötunnus: {H14}
Syntymäaika: 21.07.1977
Sukupuoli: nainen
Käyntipäivä: 02.10.2026

SYY
Pitkittynyt alaselkäkipu, joka säteilee vasempaan reiteen. Kesto yli 3 kuukautta ja kipu häiritsee unta.

ESITIEDOT
Pituus 164 cm, paino 71 kg. Tupakoi noin 5 savuketta päivässä. Työ: sairaanhoitaja, kolmivuorotyö. Kuntoutuksena fysioterapian alkuarvio ja liikuntaohjeet.

MITTAUKSET JA TULOKSET
Verenpaine 122/78 mmHg, pulssi 68/min (02.10.2026).
TSH 2,1 mU/l, 25-OH-D-vitamiini 58 nmol/l (22.09.2026). Luuntiheysmittaus (DXA) 2023: T-arvo -2,7.

POTILAAN OMA KUVAUS
"Haluaisin jaksaa töissä ja ulkoilla koiran kanssa ilman, että selkä jumittuu ja yöunet menevät."

PERUSSAIRAUDET
M54.4 Alaselkäkipu ja iskias, kesto 3 kk
M81.9 Osteoporoosi, todettu 2023
F32.0 Lievä masennustila
E03.9 Kilpirauhasen vajaatoiminta

LÄÄKITYS
- Sertraliini 50 mg tabl 1 x 1 aamulla (ATC N06AB06)
- Levotyroksiini 75 mikrog tabl 1 x 1 aamulla
- Calcichew-D3 500 mg/10 mikrog purutabl 1 x 1
- Naprokseeni 500 mg tabl 1 tarv., max 2 x vrk

ALLERGIAT
Kodeiini: pahoinvointi ja huimaus (intoleranssi)

SUUNNITELMA
Fysioterapiaa 8 käyntiä 8 viikon aikana, tavoitteena kivun hallinta ja yöunen paraneminen. Lääkärin seuranta 6 viikon kuluttua.

Testi Lääkäri
"""

FI14 = Case(
    case_id="fi14_outpatient_physio_lbp_txt",
    language="fi",
    fmt="txt",
    doc_type="outpatient_note",
    features=(
        PHYSIO,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "as_needed_dosing",
        "partial_dates",
        "intolerance",
        "allergy_reactions",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "GP note for prolonged low back pain with sciatica. Diagnoses map to the physiotherapy "
        "questionnaire's checklist: M54.4 (back pain, duration 3 months), osteoporosis M81, "
        "depression F32, thyroid E03. The codeine entry says 'intoleranssi', so it is an "
        "intolerance, not an allergy. Smoking, height and weight are context only."
    ),
    document=FI14_DOC,
    gold=extraction(
        "fi",
        patient(
            names=[
                name("LEHTINEN-TESTI, Sari Marjatta", family="LEHTINEN-TESTI", given=["Sari", "Marjatta"])
            ],
            birth_date=birth("Syntymäaika: 21.07.1977", "1977-07-21"),
            gender=gender("Sukupuoli: nainen", "female"),
            identifiers=[ident(f"Henkilötunnus: {H14}", H14, "Henkilötunnus")],
        ),
        allergies_found(
            [
                allergy(
                    "Kodeiini: pahoinvointi ja huimaus (intoleranssi)",
                    "Kodeiini",
                    type="intolerance",
                    category="medication",
                    reactions=[reaction("pahoinvointi", "huimaus")],
                )
            ]
        ),
        found(
            med(
                "Sertraliini 50 mg tabl 1 x 1 aamulla (ATC N06AB06)",
                "Sertraliini",
                code="N06AB06",
                code_system="ATC",
                strength="50 mg",
                form="tabl",
                dose=daily("1 x 1 aamulla", "1", "tabl", "1"),
            ),
            med(
                "Levotyroksiini 75 mikrog tabl 1 x 1 aamulla",
                "Levotyroksiini",
                strength="75 mikrog",
                form="tabl",
                dose=daily("1 x 1 aamulla", "1", "tabl", "1"),
            ),
            med(
                "Calcichew-D3 500 mg/10 mikrog purutabl 1 x 1",
                "Calcichew-D3",
                strength="500 mg/10 mikrog",
                form="purutabl",
                dose=daily("1 x 1", "1", "purutabl", "1"),
            ),
            med(
                "Naprokseeni 500 mg tabl 1 tarv., max 2 x vrk",
                "Naprokseeni",
                strength="500 mg",
                form="tabl",
                dose=dosage("1 tarv., max 2 x vrk", dose="1", unit="tabl", prn=True),
            ),
        ),
        found(
            cond(
                "M54.4 Alaselkäkipu ja iskias, kesto 3 kk",
                "Alaselkäkipu ja iskias",
                code="M54.4",
                note="kesto 3 kk",
            ),
            cond(
                "M81.9 Osteoporoosi, todettu 2023",
                "Osteoporoosi",
                code="M81.9",
                verification="confirmed",
                onset="2023",
            ),
            cond("F32.0 Lievä masennustila", "Lievä masennustila", code="F32.0"),
            cond("E03.9 Kilpirauhasen vajaatoiminta", "Kilpirauhasen vajaatoiminta", code="E03.9"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# fi15: physiotherapy note, HETU only, COPD + coronary disease + hypertension, decimal comma
# ---------------------------------------------------------------------------------------------

H15 = hetu("1959-04-30", 941)
FI15_DOC = f"""KUVITTEELAN TERVEYSASEMA / Hoitajan ja lääkärin vastaanotto
SYNTEETTINEN TESTIASIAKIRJA - EI OIKEA POTILAS

VASTAANOTTOKIRJAUS

POTILAS
Nimi: VIRTANEN-TESTI, Pentti Johannes
Henkilötunnus: {H15}
Taustatiedot: 67-vuotias mies, eläkkeellä.

KÄYNNIN SYY
Alaselän jumi ja kipu kävellessä, pahentunut parin kuukauden aikana. Fysioterapeutin arvio toivottu.

MITAT JA ELINTAVAT
Pituus 175 cm, paino 88,5 kg. Tupakointi lopetettu 2019, aiemmin noin 30 askivuotta. Alkoholia ei käytä.

MITTAUKSET JA TULOKSET
Verenpaine 146/88 mmHg, pulssi 78/min, SpO2 93 % huoneilmassa (05.10.2026).
Spirometria 09/2026: FEV1 62 % viitearvosta. Hb 148 g/l (28.09.2026).

LAITTEET JA APUVÄLINEET
Inhalaatiovälikammio (Volumatic) ja kävelykeppi.

HOITOTAHTO
Potilaalla on hoitotahto (laadittu 03/2026): ei pitkäaikaista hengityskonehoitoa.

HUOMIO
Kaatumisriski, kaatui kerran elokuussa 2026.

DIAGNOOSIT
M54.5 Alaselkäkipu
J44.9 Keuhkoahtaumatauti (COPD)
I25.1 Sepelvaltimotauti, todettu 2018
I10 Verenpainetauti

LÄÄKITYS
- Tiotropium 18 mikrog inh kapseli 1 x 1 (ATC R03BB04)
- Salbutamoli 0,1 mg/annos inh 1-2 annosta tarv.
- Asetyylisalisyylihappo 100 mg tabl 1 x 1 aamulla
- Bisoprololi 5 mg tabl 1 x 1
- Rosuvastatiini 10 mg tabl 1 x 1 iltaisin

LOPETETUT LÄÄKKEET
- Tramadoli 50 mg, lopetettu 09/2026 pahoinvoinnin vuoksi

ALLERGIAT
Ei tiedossa.

Testi Lääkäri
"""

FI15 = Case(
    case_id="fi15_outpatient_physio_copd_txt",
    language="fi",
    fmt="txt",
    doc_type="outpatient_note",
    features=(
        PHYSIO,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "hetu_without_birth_date",
        "stopped_medication",
        "as_needed_dosing",
        "partial_dates",
        "decimal_comma",
        "none_known_allergies",
        "gender_stated",
    ),
    notes=(
        "Physiotherapy-bound note. Also carries vital signs, a spirometry and lab result, devices, "
        "an advance directive and an alert (a fall risk, not a problem); none is in the schema. COPD (J44), coronary disease (I25) and hypertension (I10) all "
        "fall under the checklist. Only a HETU is given, so birth_date is null in gold (D-10); "
        "'67-vuotias mies' states the gender. A bare 'Ei tiedossa.' under the allergy heading is "
        "an explicit none-known statement, medium confidence, scope all. Tramadol is a stopped "
        "medication."
    ),
    document=FI15_DOC,
    gold=extraction(
        "fi",
        patient(
            names=[
                name(
                    "VIRTANEN-TESTI, Pentti Johannes",
                    family="VIRTANEN-TESTI",
                    given=["Pentti", "Johannes"],
                )
            ],
            birth_date=None,
            gender=gender("67-vuotias mies", "male"),
            identifiers=[ident(f"Henkilötunnus: {H15}", H15, "Henkilötunnus")],
        ),
        no_known_allergies("Ei tiedossa.", "all", confidence="medium"),
        found(
            med(
                "Tiotropium 18 mikrog inh kapseli 1 x 1 (ATC R03BB04)",
                "Tiotropium",
                code="R03BB04",
                code_system="ATC",
                strength="18 mikrog",
                form="inh kapseli",
                dose=daily("1 x 1", "1", "kapseli", "1"),
            ),
            med(
                "Salbutamoli 0,1 mg/annos inh 1-2 annosta tarv.",
                "Salbutamoli",
                strength="0,1 mg/annos",
                form="inh",
                dose=dosage("1-2 annosta tarv.", unit="annosta", prn=True),
            ),
            med(
                "Asetyylisalisyylihappo 100 mg tabl 1 x 1 aamulla",
                "Asetyylisalisyylihappo",
                strength="100 mg",
                form="tabl",
                dose=daily("1 x 1 aamulla", "1", "tabl", "1"),
            ),
            med(
                "Bisoprololi 5 mg tabl 1 x 1",
                "Bisoprololi",
                strength="5 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Rosuvastatiini 10 mg tabl 1 x 1 iltaisin",
                "Rosuvastatiini",
                strength="10 mg",
                form="tabl",
                dose=daily("1 x 1 iltaisin", "1", "tabl", "1"),
            ),
            med(
                "Tramadoli 50 mg, lopetettu 09/2026 pahoinvoinnin vuoksi",
                "Tramadoli",
                strength="50 mg",
                status="stopped",
                end="2026-09",
                note="pahoinvoinnin vuoksi",
            ),
        ),
        found(
            cond("M54.5 Alaselkäkipu", "Alaselkäkipu", code="M54.5"),
            cond("J44.9 Keuhkoahtaumatauti (COPD)", "Keuhkoahtaumatauti", code="J44.9", note="COPD"),
            cond(
                "I25.1 Sepelvaltimotauti, todettu 2018",
                "Sepelvaltimotauti",
                code="I25.1",
                verification="confirmed",
                onset="2018",
            ),
            cond("I10 Verenpainetauti", "Verenpainetauti", code="I10"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# sv07: physiotherapy referral in Swedish, asthma + psoriasis + migraine + obesity
# ---------------------------------------------------------------------------------------------

H_SV07 = hetu("1982-09-03", 953)
SV07_DOC = f"""KUVITTEELAN HÄLSOCENTRAL / Mottagning
SYNTETISKT TESTDOKUMENT - INTE EN RIKTIG PATIENT

REMISS TILL FYSIOTERAPI

Patient: SJÖBERG-TEST, Anna Maria
Personnummer: {H_SV07}
Födelsedatum: 03.09.1982
Kön: kvinna
Remissdatum: 05.10.2026

ORSAK TILL REMISSEN
Ländryggssmärta sedan cirka 2 månader, värre vid långvarigt stående. Ingen utstrålning till benen. Önskar fysioterapeutens bedömning och träningsprogram.

BAKGRUND
Längd 168 cm, vikt 82 kg. Röker inte. Arbetar som lärare.
Vaccinationer: dTp-vaccin 2019, influensavaccin 10/2025, covid-19-vaccin 2024.
Operationer: appendektomi 2008.

MÄTVÄRDEN
Blodtryck 126/80 mmHg, puls 70/min, BMI 29,0 (05.10.2026).

DIAGNOSER
M54.5 Ländryggssmärta
J45.9 Astma
L40.0 Psoriasis vulgaris
G43.9 Migrän
E66.9 Övervikt

MEDICINERING
- Budesonid/formoterol 160/4,5 mikrog inh 1 puff x 2 (ATC R03AK07)
- Salbutamol 0,1 mg/dos inh 1-2 doser vid behov
- Daivobet salva vid behov på plack
- Sumatriptan 50 mg tabl 1 tabl vid behov vid migrän

ALLERGIER
Inga kända läkemedelsallergier.
Björkpollenallergi: rinit och ögonsymtom

Testläkare, specialist i allmänmedicin
"""

SV07 = Case(
    case_id="sv07_referral_physio_lbp_txt",
    language="sv",
    fmt="txt",
    doc_type="referral_letter",
    features=(
        PHYSIO,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "as_needed_dosing",
        "decimal_comma",
        "procedure_distractor",
        "allergy_reactions",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "Swedish physiotherapy referral. Also carries vaccinations with dates, an appendectomy "
        "(a procedure, not a problem) and vital signs; none is in the schema. Asthma J45, psoriasis L40, overweight E66 and migraine G43 "
        "fall under the checklist. A drug-scoped none-known statement stands next to a pollen "
        "allergy (D-7); 'Björkpollenallergi' loses its 'allergi' ending in substance_text. "
        "The indication written inside the sumatriptan dosing line stays in the dosage text."
    ),
    document=SV07_DOC,
    gold=extraction(
        "sv",
        patient(
            names=[name("SJÖBERG-TEST, Anna Maria", family="SJÖBERG-TEST", given=["Anna", "Maria"])],
            birth_date=birth("Födelsedatum: 03.09.1982", "1982-09-03"),
            gender=gender("Kön: kvinna", "female"),
            identifiers=[ident(f"Personnummer: {H_SV07}", H_SV07, "Personnummer")],
        ),
        allergies_found(
            [
                allergy(
                    "Björkpollenallergi: rinit och ögonsymtom",
                    "Björkpollen",
                    type="allergy",
                    category="environment",
                    reactions=[reaction("rinit", "ögonsymtom")],
                )
            ],
            [nka_statement("Inga kända läkemedelsallergier.", "medication")],
        ),
        found(
            med(
                "Budesonid/formoterol 160/4,5 mikrog inh 1 puff x 2 (ATC R03AK07)",
                "Budesonid/formoterol",
                code="R03AK07",
                code_system="ATC",
                strength="160/4,5 mikrog",
                form="inh",
                dose=daily("1 puff x 2", "1", "puff", "2"),
            ),
            med(
                "Salbutamol 0,1 mg/dos inh 1-2 doser vid behov",
                "Salbutamol",
                strength="0,1 mg/dos",
                form="inh",
                dose=dosage("1-2 doser vid behov", unit="doser", prn=True),
            ),
            med(
                "Daivobet salva vid behov på plack",
                "Daivobet",
                form="salva",
                dose=dosage("vid behov på plack", prn=True),
            ),
            med(
                "Sumatriptan 50 mg tabl 1 tabl vid behov vid migrän",
                "Sumatriptan",
                strength="50 mg",
                form="tabl",
                dose=dosage("1 tabl vid behov vid migrän", dose="1", unit="tabl", prn=True),
            ),
        ),
        found(
            cond("M54.5 Ländryggssmärta", "Ländryggssmärta", code="M54.5"),
            cond("J45.9 Astma", "Astma", code="J45.9"),
            cond("L40.0 Psoriasis vulgaris", "Psoriasis vulgaris", code="L40.0"),
            cond("G43.9 Migrän", "Migrän", code="G43.9"),
            cond("E66.9 Övervikt", "Övervikt", code="E66.9"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# en07: physiotherapy referral in English, type 1 diabetes + anxiety + IBS
# ---------------------------------------------------------------------------------------------

H_EN07 = hetu("1990-05-14", 962)
EN07_DOC = f"""KUVITTEELA HEALTH CENTRE / Outpatient clinic
SYNTHETIC TEST DOCUMENT - NOT A REAL PATIENT

REFERRAL TO PHYSIOTHERAPY

Patient: GREENWOOD-TEST, Daniel James
Personal identity code: {H_EN07}
DOB: 14.05.1990
Sex: M
Date: 07.10.2026

REASON FOR REFERRAL
Low back pain since April 2026, worse after sitting at a desk for long periods. No leg symptoms. Please assess and advise on an exercise programme.

BACKGROUND
Height 183 cm, weight 79 kg. Non-smoker. Office worker.
Immunisations: tetanus booster 2021, influenza vaccine 10/2025.

VITAL SIGNS AND RESULTS
BP 124/78 mmHg, pulse 66/min, BMI 23.6 (07.10.2026).
HbA1c 58 mmol/mol, eGFR above 90 ml/min (23.09.2026).

DEVICES
Continuous glucose monitor (FreeStyle Libre 2).

DIAGNOSES
M54.5 Low back pain, onset 04/2026
E10.9 Type 1 diabetes mellitus, diagnosed 2008
F41.1 Generalised anxiety disorder
K58.9 Irritable bowel syndrome

MEDICATION
- Insulin glargine 100 U/ml 22 units OD (ATC A10AE04)
- Insulin aspart 100 U/ml with meals per carbohydrate count
- Escitalopram 10 mg tabl 1 OD
- Ibuprofen 400 mg tabl 1 PRN, max 3 per day

ALLERGIES
No known allergies.

PLAN
Physiotherapy 6 sessions over 6 weeks; goals: sit for 90 minutes at work without pain, return to running. Review by the GP after the course.

Dr Test, general practitioner
"""

EN07 = Case(
    case_id="en07_referral_physio_lbp_txt",
    language="en",
    fmt="txt",
    doc_type="referral_letter",
    features=(
        PHYSIO,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "as_needed_dosing",
        "partial_dates",
        "abbreviations",
        "none_known_allergies",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "English physiotherapy referral. Also carries vaccinations, vital signs, lab results, a "
        "glucose-monitor device and a plan of care with goals; none is in the schema. Type 1 diabetes E10, anxiety F41 and IBS K58 fall under the "
        "checklist; M54.5 gives the onset. 'OD' and 'PRN' dosing abbreviations. 'No known "
        "allergies.' is an unscoped none-known statement (scope all)."
    ),
    document=EN07_DOC,
    gold=extraction(
        "en",
        patient(
            names=[
                name("GREENWOOD-TEST, Daniel James", family="GREENWOOD-TEST", given=["Daniel", "James"])
            ],
            birth_date=birth("DOB: 14.05.1990", "1990-05-14"),
            gender=gender("Sex: M", "male"),
            identifiers=[
                ident(
                    f"Personal identity code: {H_EN07}",
                    H_EN07,
                    "Personal identity code",
                )
            ],
        ),
        no_known_allergies("No known allergies.", "all"),
        found(
            med(
                "Insulin glargine 100 U/ml 22 units OD (ATC A10AE04)",
                "Insulin glargine",
                code="A10AE04",
                code_system="ATC",
                strength="100 U/ml",
                dose=daily("22 units OD", "22", "units", "1"),
            ),
            med(
                "Insulin aspart 100 U/ml with meals per carbohydrate count",
                "Insulin aspart",
                strength="100 U/ml",
                dose=dosage("with meals per carbohydrate count"),
            ),
            med(
                "Escitalopram 10 mg tabl 1 OD",
                "Escitalopram",
                strength="10 mg",
                form="tabl",
                dose=daily("1 OD", "1", "tabl", "1"),
            ),
            med(
                "Ibuprofen 400 mg tabl 1 PRN, max 3 per day",
                "Ibuprofen",
                strength="400 mg",
                form="tabl",
                dose=dosage("1 PRN, max 3 per day", dose="1", unit="tabl", prn=True),
            ),
        ),
        found(
            cond(
                "M54.5 Low back pain, onset 04/2026",
                "Low back pain",
                code="M54.5",
                onset="2026-04",
            ),
            cond(
                "E10.9 Type 1 diabetes mellitus, diagnosed 2008",
                "Type 1 diabetes mellitus",
                code="E10.9",
                verification="confirmed",
                onset="2008",
            ),
            cond("F41.1 Generalised anxiety disorder", "Generalised anxiety disorder", code="F41.1"),
            cond("K58.9 Irritable bowel syndrome", "Irritable bowel syndrome", code="K58.9"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# fi16: maternity clinic referral, type 1 diabetes + hypothyroidism + asthma, supplements
# ---------------------------------------------------------------------------------------------

H16 = hetu("1995-03-05", 971)
FI16_DOC = f"""KUVITTEELAN TERVEYSASEMA / Vastaanotto
SYNTEETTINEN TESTIASIAKIRJA - EI OIKEA POTILAS

LÄHETE ÄITIYSNEUVOLAAN

Potilas: HEINONEN-TESTI, Laura Katariina
Henkilötunnus: {H16}
Syntymäaika: 05.03.1995
Sukupuoli: nainen
Lähetepäivä: 08.10.2026

RASKAUS
Positiivinen raskaustesti 29.09.2026. Viimeisten kuukautisten alkamispäivä 11.08.2026, lasketun ajan arvio 18.05.2027.
Aiemmat raskaudet: 1, synnytyksiä 1 (alateitse 2022, lapsi 3 420 g). Ei keskenmenoja eikä keskeytyksiä.
Pituus 166 cm, paino ennen raskautta 64 kg.
Rokotukset: MPR-rokote 1997 ja 2002, vesirokko sairastettu lapsena.
Yhteyshenkilö: Jukka Heinonen-Testi (puoliso), puh. 040 000 0000.

MITTAUKSET JA TULOKSET
Verenpaine 118/72 mmHg, pulssi 76/min (08.10.2026).
HbA1c 49 mmol/mol, TSH 1,8 mU/l (29.09.2026).

LAITTEET
Jatkuva sokeriseuranta (FreeStyle Libre 2).

DIAGNOOSIT
Z32.1 Raskaus todettu (rv 8+2)
E10.9 Tyypin 1 diabetes, todettu 2009
E03.9 Kilpirauhasen vajaatoiminta
J45.9 Astma
E10.1 Diabeettinen ketoasidoosi 2013, parantunut

LÄÄKITYS
- Insuliini glargiini 100 yks/ml 18 yks 1 x 1 iltaisin (ATC A10AE04)
- Insuliini aspartti 100 yks/ml aterioille hiilihydraattilaskennan mukaan
- Levotyroksiini 100 mikrog tabl 1 x 1 aamulla
- Budesonidi 200 mikrog/annos inh 1 annos x 2
- Salbutamoli 0,1 mg/annos inh 1-2 annosta tarv.
- Foolihappo 0,4 mg tabl 1 x 1 (ATC B03BB01)
- Kolekalsiferoli 20 mikrog tabl 1 x 1 (ATC A11CC05)

ALLERGIAT
Penisilliini: ihottuma lapsena

SUUNNITELMA
Neuvolakäynnit tiheämmin, sokeritasapainon seuranta. Kontrolli diabetespoliklinikalla raskausviikolla 12.

Testi Lääkäri, yleislääketieteen erikoislääkäri
"""

FI16 = Case(
    case_id="fi16_referral_maternity_t1dm_txt",
    language="fi",
    fmt="txt",
    doc_type="referral_letter",
    features=(
        MATERNITY,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "resolved_condition",
        "as_needed_dosing",
        "partial_dates",
        "abbreviations",
        "allergy_reactions",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "GP referral to the maternity clinic. Also carries vital signs, lab results, a glucose "
        "monitor device and a plan of care (context only), and a resolved ketoacidosis in 2013 "
        "(past problem). Diabetes E10, thyroid E03 and asthma J45 fall under "
        "the maternity checklist; folic acid (B03BB) and vitamin D (A11CC) answer the supplement "
        "questions. The pregnancy is a problem (Z32.1, written as a diagnosis line). Pregnancy "
        "history, LMP, height, weight, vaccinations and the contact person are context only (not in "
        "the schema). 'Ei keskenmenoja eikä keskeytyksiä' is not a problem or a statement."
    ),
    document=FI16_DOC,
    gold=extraction(
        "fi",
        patient(
            names=[
                name(
                    "HEINONEN-TESTI, Laura Katariina",
                    family="HEINONEN-TESTI",
                    given=["Laura", "Katariina"],
                )
            ],
            birth_date=birth("Syntymäaika: 05.03.1995", "1995-03-05"),
            gender=gender("Sukupuoli: nainen", "female"),
            identifiers=[ident(f"Henkilötunnus: {H16}", H16, "Henkilötunnus")],
        ),
        allergies_found(
            [
                allergy(
                    "Penisilliini: ihottuma lapsena",
                    "Penisilliini",
                    category="medication",
                    reactions=[reaction("ihottuma")],
                )
            ]
        ),
        found(
            med(
                "Insuliini glargiini 100 yks/ml 18 yks 1 x 1 iltaisin (ATC A10AE04)",
                "Insuliini glargiini",
                code="A10AE04",
                code_system="ATC",
                strength="100 yks/ml",
                dose=daily("18 yks 1 x 1 iltaisin", "18", "yks", "1"),
            ),
            med(
                "Insuliini aspartti 100 yks/ml aterioille hiilihydraattilaskennan mukaan",
                "Insuliini aspartti",
                strength="100 yks/ml",
                dose=dosage("aterioille hiilihydraattilaskennan mukaan"),
            ),
            med(
                "Levotyroksiini 100 mikrog tabl 1 x 1 aamulla",
                "Levotyroksiini",
                strength="100 mikrog",
                form="tabl",
                dose=daily("1 x 1 aamulla", "1", "tabl", "1"),
            ),
            med(
                "Budesonidi 200 mikrog/annos inh 1 annos x 2",
                "Budesonidi",
                strength="200 mikrog/annos",
                form="inh",
                dose=daily("1 annos x 2", "1", "annos", "2"),
            ),
            med(
                "Salbutamoli 0,1 mg/annos inh 1-2 annosta tarv.",
                "Salbutamoli",
                strength="0,1 mg/annos",
                form="inh",
                dose=dosage("1-2 annosta tarv.", unit="annosta", prn=True),
            ),
            med(
                "Foolihappo 0,4 mg tabl 1 x 1 (ATC B03BB01)",
                "Foolihappo",
                code="B03BB01",
                code_system="ATC",
                strength="0,4 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Kolekalsiferoli 20 mikrog tabl 1 x 1 (ATC A11CC05)",
                "Kolekalsiferoli",
                code="A11CC05",
                code_system="ATC",
                strength="20 mikrog",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
        ),
        found(
            cond("Z32.1 Raskaus todettu (rv 8+2)", "Raskaus todettu", code="Z32.1", note="rv 8+2"),
            cond(
                "E10.9 Tyypin 1 diabetes, todettu 2009",
                "Tyypin 1 diabetes",
                code="E10.9",
                verification="confirmed",
                onset="2009",
            ),
            cond("E03.9 Kilpirauhasen vajaatoiminta", "Kilpirauhasen vajaatoiminta", code="E03.9"),
            cond("J45.9 Astma", "Astma", code="J45.9"),
            cond(
                "E10.1 Diabeettinen ketoasidoosi 2013, parantunut",
                "Diabeettinen ketoasidoosi",
                code="E10.1",
                status="resolved",
                onset="2013",
            ),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# fi17: maternity clinic intake note, HETU only, hypertension + epilepsy + earlier thrombosis
# ---------------------------------------------------------------------------------------------

H17 = hetu("1989-11-23", 982)
FI17_DOC = f"""KUVITTEELAN NEUVOLA / Äitiysneuvola
SYNTEETTINEN TESTIASIAKIRJA - EI OIKEA POTILAS

ÄITIYSNEUVOLAN ALOITUSKÄYNTI

Nimi: PELTONEN-TESTI, Johanna Elisabet
Henkilötunnus: {H17}
Sukupuoli: nainen
Käyntipäivä: 08.10.2026

RASKAUS JA SYNNYTYSHISTORIA
Raskaus 3, synnytyksiä 2: alateitse 2016 ja keisarinleikkauksella 2019. Yksi keskenmeno 2020. Viimeisten kuukautisten alkamispäivä 02.09.2026, lasketun ajan arvio 09.06.2027.
Pituus 171 cm, paino ennen raskautta 78 kg. Ei tupakoi.
Rokotukset: MPR-rokote kahdesti, vesirokkorokote 2012.
Yhteyshenkilö: Mika Esimerkki-Testi (aviomies), puh. 040 000 0001.

MITTAUKSET JA TULOKSET
Verenpaine 128/82 mmHg, pulssi 82/min (08.10.2026).
Lamotrigiinipitoisuus 8,2 mg/l, Hb 121 g/l, ferritiini 18 µg/l (05.10.2026).

POTILAAN TOIVEET
Toivon alatiesynnytystä, jos se on mahdollista, ja että puoliso on mukana synnytyksessä. Pelkään kohtauksia synnytyksen aikana.

HUOMIO
Epilepsia ja antikoagulaatiohoito: erityisseuranta raskauden ajan, ilmoita synnytyssairaalaan.

DIAGNOOSIT
Z32.1 Raskaus todettu (rv 5+1)
I10 Verenpainetauti, todettu 2018
G40.9 Epilepsia, todettu 2005
I80.2 Syvä laskimotukos, 2021

LÄÄKITYS
- Labetaloli 100 mg tabl 1 x 2
- Lamotrigiini 100 mg tabl 1 x 2 (ATC N03AX09)
- Enoksapariini 40 mg inj 1 x 1 s.c.
- Foolihappo 4 mg tabl 1 x 1 (ATC B03BB01)
- Kolekalsiferoli 20 mikrog tabl 1 x 1 (ATC A11CC05)
- Kalsiumkarbonaatti 500 mg tabl 1 x 1 (ATC A12AA04)

LOPETETUT LÄÄKKEET
- Enalapriili 10 mg, lopetettu 09/2026 raskauden vuoksi

ALLERGIAT
Ei tiedossa olevia allergioita.

SUUNNITELMA
Äitiysneuvolakäynnit 2 viikon välein, verenpaineen ja lääkepitoisuuden seuranta. Lähete neurologin ja synnytyslääkärin yhteiskontrolliin viikolla 12.

Testi Terveydenhoitaja
"""

FI17 = Case(
    case_id="fi17_maternity_intake_epilepsy_txt",
    language="fi",
    fmt="txt",
    doc_type="outpatient_note",
    features=(
        MATERNITY,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "hetu_without_birth_date",
        "stopped_medication",
        "partial_dates",
        "procedure_distractor",
        "none_known_allergies",
        "gender_stated",
    ),
    notes=(
        "Maternity clinic intake note. Also carries vital signs, lab results, the patient's own "
        "wishes, an alert and a plan of care (context only; the alert is not a problem). Hypertension I10 and epilepsy G40 fall under the maternity "
        "checklist; a past thrombosis (I80) is the 'veritulppa' option. Folic acid, vitamin D and "
        "calcium answer three supplement questions. Enalapril is a stopped medication. The "
        "caesarean section is a procedure and the miscarriage is history, so neither is a "
        "problem. HETU only, so birth_date is null (D-10). 'Ei tiedossa olevia allergioita' is an "
        "unscoped none-known statement (scope all)."
    ),
    document=FI17_DOC,
    gold=extraction(
        "fi",
        patient(
            names=[
                name(
                    "PELTONEN-TESTI, Johanna Elisabet",
                    family="PELTONEN-TESTI",
                    given=["Johanna", "Elisabet"],
                )
            ],
            birth_date=None,
            gender=gender("Sukupuoli: nainen", "female"),
            identifiers=[ident(f"Henkilötunnus: {H17}", H17, "Henkilötunnus")],
        ),
        no_known_allergies("Ei tiedossa olevia allergioita.", "all"),
        found(
            med(
                "Labetaloli 100 mg tabl 1 x 2",
                "Labetaloli",
                strength="100 mg",
                form="tabl",
                dose=daily("1 x 2", "1", "tabl", "2"),
            ),
            med(
                "Lamotrigiini 100 mg tabl 1 x 2 (ATC N03AX09)",
                "Lamotrigiini",
                code="N03AX09",
                code_system="ATC",
                strength="100 mg",
                form="tabl",
                dose=daily("1 x 2", "1", "tabl", "2"),
            ),
            med(
                "Enoksapariini 40 mg inj 1 x 1 s.c.",
                "Enoksapariini",
                strength="40 mg",
                form="inj",
                dose=daily("1 x 1 s.c.", "1", "inj", "1", route="s.c."),
            ),
            med(
                "Foolihappo 4 mg tabl 1 x 1 (ATC B03BB01)",
                "Foolihappo",
                code="B03BB01",
                code_system="ATC",
                strength="4 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Kolekalsiferoli 20 mikrog tabl 1 x 1 (ATC A11CC05)",
                "Kolekalsiferoli",
                code="A11CC05",
                code_system="ATC",
                strength="20 mikrog",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Kalsiumkarbonaatti 500 mg tabl 1 x 1 (ATC A12AA04)",
                "Kalsiumkarbonaatti",
                code="A12AA04",
                code_system="ATC",
                strength="500 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Enalapriili 10 mg, lopetettu 09/2026 raskauden vuoksi",
                "Enalapriili",
                strength="10 mg",
                status="stopped",
                end="2026-09",
                note="raskauden vuoksi",
            ),
        ),
        found(
            cond("Z32.1 Raskaus todettu (rv 5+1)", "Raskaus todettu", code="Z32.1", note="rv 5+1"),
            cond(
                "I10 Verenpainetauti, todettu 2018",
                "Verenpainetauti",
                code="I10",
                verification="confirmed",
                onset="2018",
            ),
            cond(
                "G40.9 Epilepsia, todettu 2005",
                "Epilepsia",
                code="G40.9",
                verification="confirmed",
                onset="2005",
            ),
            cond("I80.2 Syvä laskimotukos, 2021", "Syvä laskimotukos", code="I80.2", onset="2021"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# fi18: maternity clinic note as PDF, Crohn's disease + iron deficiency anaemia, B12
# ---------------------------------------------------------------------------------------------

H18 = hetu("1998-01-14", 989)
FI18_DOC = [
    [
        "# KUVITTEELAN NEUVOLA / Äitiysneuvola",
        "SYNTEETTINEN TESTIASIAKIRJA - EI OIKEA POTILAS",
        "",
        "# ÄITIYSNEUVOLAN ALOITUSKÄYNTI",
        "",
        "Nimi: NIEMINEN-TESTI, Elina Sofia",
        f"Henkilötunnus: {H18}",
        "Syntymäaika: 14.01.1998",
        "Sukupuoli: nainen",
        "Käyntipäivä: 08.10.2026",
        "",
        "# RASKAUS",
        "Ensiraskaus. Viimeisten kuukautisten alkamispäivä 19.07.2026, laskettu aika 25.04.2027.",
        "Pituus 169 cm, paino ennen raskautta 59 kg. Ei tupakoi. Ei alkoholia.",
        "Rokotukset: MPR-rokote 2000 ja 2004, influenssarokote 10/2026, koronarokote 2023.",
        "Vesirokko sairastettu.",
        "Yhteyshenkilö: Aaro Nieminen-Testi (puoliso), puh. 040 000 0002.",
        "Suolen osaresektio 2019 Crohnin taudin vuoksi.",
        "",
        "# MITTAUKSET JA TULOKSET",
        "Verenpaine 110/68 mmHg, pulssi 80/min (08.10.2026).",
        "Hb 108 g/l, ferritiini 9 µg/l, CRP 4 mg/l (06.10.2026).",
        "",
        "# TOIMINTAKYKY",
        "Työkykyinen, tekee toimistotyötä. Väsyy iltapäivisin, mutta selviytyy arjesta itsenäisesti.",
        "",
        "# DIAGNOOSIT",
        "Z32.1 Raskaus todettu (rv 11+4)",
        "K50.9 Crohnin tauti, todettu 2018",
        "D50.9 Raudanpuuteanemia",
        "N39.0 Virtsatieinfektio 2025, parantunut",
        "",
        "# LÄÄKITYS",
        "- Mesalatsiini 500 mg tabl 1 x 3 (ATC A07EC02)",
        "- Atsatiopriini 50 mg tabl 1 x 1 aamulla",
        "- Rauta 100 mg tabl 1 x 1",
        "- Syanokobalamiini 1 mg inj kerran kuukaudessa (ATC B03BA01)",
        "- Foolihappo 0,4 mg tabl 1 x 1 (ATC B03BB01)",
        "- Kolekalsiferoli 20 mikrog tabl 1 x 1 (ATC A11CC05)",
        "",
        "# ALLERGIAT",
        "Kala-allergia: nokkosihottuma",
        "",
        "Testi Terveydenhoitaja",
    ]
]

FI18 = Case(
    case_id="fi18_maternity_intake_crohn_pdf",
    language="fi",
    fmt="pdf",
    doc_type="outpatient_note",
    features=(
        MATERNITY,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "procedure_distractor",
        "resolved_condition",
        "partial_dates",
        "allergy_reactions",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "One-page PDF intake note. Also carries dated vaccinations, vital signs, lab results and "
        "functional status (context only), and a resolved urinary tract infection (past problem). Crohn's disease K50 is the bowel-disease option; iron deficiency "
        "anaemia D50, B12 (B03BA) and folic acid and vitamin D answer the supplement questions. "
        "The bowel resection is a procedure and is not a problem. 'Kala-allergia' loses its "
        "'allergia' ending in substance_text."
    ),
    document=FI18_DOC,
    gold=extraction(
        "fi",
        patient(
            names=[
                name(
                    "NIEMINEN-TESTI, Elina Sofia",
                    family="NIEMINEN-TESTI",
                    given=["Elina", "Sofia"],
                )
            ],
            birth_date=birth("Syntymäaika: 14.01.1998", "1998-01-14"),
            gender=gender("Sukupuoli: nainen", "female"),
            identifiers=[ident(f"Henkilötunnus: {H18}", H18, "Henkilötunnus")],
        ),
        allergies_found(
            [
                allergy(
                    "Kala-allergia: nokkosihottuma",
                    "Kala",
                    type="allergy",
                    category="food",
                    reactions=[reaction("nokkosihottuma")],
                )
            ]
        ),
        found(
            med(
                "Mesalatsiini 500 mg tabl 1 x 3 (ATC A07EC02)",
                "Mesalatsiini",
                code="A07EC02",
                code_system="ATC",
                strength="500 mg",
                form="tabl",
                dose=daily("1 x 3", "1", "tabl", "3"),
            ),
            med(
                "Atsatiopriini 50 mg tabl 1 x 1 aamulla",
                "Atsatiopriini",
                strength="50 mg",
                form="tabl",
                dose=daily("1 x 1 aamulla", "1", "tabl", "1"),
            ),
            med(
                "Rauta 100 mg tabl 1 x 1",
                "Rauta",
                strength="100 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Syanokobalamiini 1 mg inj kerran kuukaudessa (ATC B03BA01)",
                "Syanokobalamiini",
                code="B03BA01",
                code_system="ATC",
                strength="1 mg",
                form="inj",
                dose=dosage("kerran kuukaudessa"),
            ),
            med(
                "Foolihappo 0,4 mg tabl 1 x 1 (ATC B03BB01)",
                "Foolihappo",
                code="B03BB01",
                code_system="ATC",
                strength="0,4 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Kolekalsiferoli 20 mikrog tabl 1 x 1 (ATC A11CC05)",
                "Kolekalsiferoli",
                code="A11CC05",
                code_system="ATC",
                strength="20 mikrog",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
        ),
        found(
            cond("Z32.1 Raskaus todettu (rv 11+4)", "Raskaus todettu", code="Z32.1", note="rv 11+4"),
            cond(
                "K50.9 Crohnin tauti, todettu 2018",
                "Crohnin tauti",
                code="K50.9",
                verification="confirmed",
                onset="2018",
            ),
            cond("D50.9 Raudanpuuteanemia", "Raudanpuuteanemia", code="D50.9"),
            cond(
                "N39.0 Virtsatieinfektio 2025, parantunut",
                "Virtsatieinfektio",
                code="N39.0",
                status="resolved",
                onset="2025",
            ),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# sv08: maternity clinic referral in Swedish, asthma + ulcerative colitis + anaemia
# ---------------------------------------------------------------------------------------------

H_SV08 = hetu("1993-06-27", 994)
SV08_DOC = f"""KUVITTEELAN HÄLSOCENTRAL / Mottagning
SYNTETISKT TESTDOKUMENT - INTE EN RIKTIG PATIENT

REMISS TILL MÖDRARÅDGIVNINGEN

Patient: STRÖM-TEST, Karin Helena
Personnummer: {H_SV08}
Födelsedatum: 27.06.1993
Kön: kvinna
Remissdatum: 08.10.2026

GRAVIDITET
Positivt graviditetstest 03.10.2026. Första dagen av sista menstruationen 06.08.2026, beräknad förlossning 13.05.2027.
Tidigare graviditeter: 0. Längd 172 cm, vikt före graviditeten 66 kg. Röker inte.
Vaccinationer: MPR-vaccin 1995 och 2000, vattkoppor genomgångna.
Kontaktperson: Erik Exempel-Test (make), tel 040 000 0003.
Operationer: appendektomi 2008. Koloskopi 03/2026.

MÄTVÄRDEN OCH RESULTAT
Blodtryck 112/70 mmHg, puls 74/min (08.10.2026).
Hb 118 g/l, ferritin 14 µg/l, fekalt kalprotektin 45 µg/g (05.10.2026).

HJÄLPMEDEL
Spacer (Volumatic) till inhalatorn.

DIAGNOSER
Z32.1 Graviditet bekräftad (v 9+0)
J45.9 Astma
K51.9 Ulcerös kolit, diagnostiserad 2019
D50.9 Järnbristanemi

MEDICINERING
- Budesonid/formoterol 160/4,5 mikrog inh 1 puff x 2 (ATC R03AK07)
- Salbutamol 0,1 mg/dos inh 1-2 doser vid behov
- Mesalazin 500 mg tabl 1 x 3
- Järn 100 mg tabl 1 x 1
- Folsyra 0,4 mg tabl 1 x 1 (ATC B03BB01)
- D-vitamin 20 mikrog tabl 1 x 1 (ATC A11CC05)
- Kalcium 500 mg tabl 1 x 1 (ATC A12AA04)

ALLERGIER
Inga kända läkemedelsallergier.
Nötallergi: svullnad i läpparna

PLAN
Täta besök på mödrarådgivningen, uppföljning av järnvärden. Kontroll hos gastroenterolog i vecka 14.

Testläkare, specialist i allmänmedicin
"""

SV08 = Case(
    case_id="sv08_referral_maternity_asthma_txt",
    language="sv",
    fmt="txt",
    doc_type="referral_letter",
    features=(
        MATERNITY,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "as_needed_dosing",
        "decimal_comma",
        "procedure_distractor",
        "nkda_plus_food_allergy",
        "allergy_reactions",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "Swedish maternity clinic referral. Also carries procedures (appendectomy, colonoscopy; "
        "not problems), vital signs, lab results, an inhaler spacer and a plan of care (context "
        "only). Asthma J45 and ulcerative colitis K51 fall under the "
        "maternity checklist; folic acid, vitamin D and calcium answer three supplement questions. "
        "A drug-scoped none-known statement stands next to a nut allergy (D-7). 'Tidigare "
        "graviditeter: 0' is context only."
    ),
    document=SV08_DOC,
    gold=extraction(
        "sv",
        patient(
            names=[name("STRÖM-TEST, Karin Helena", family="STRÖM-TEST", given=["Karin", "Helena"])],
            birth_date=birth("Födelsedatum: 27.06.1993", "1993-06-27"),
            gender=gender("Kön: kvinna", "female"),
            identifiers=[ident(f"Personnummer: {H_SV08}", H_SV08, "Personnummer")],
        ),
        allergies_found(
            [
                allergy(
                    "Nötallergi: svullnad i läpparna",
                    "Nöt",
                    type="allergy",
                    category="food",
                    reactions=[reaction("svullnad i läpparna")],
                )
            ],
            [nka_statement("Inga kända läkemedelsallergier.", "medication")],
        ),
        found(
            med(
                "Budesonid/formoterol 160/4,5 mikrog inh 1 puff x 2 (ATC R03AK07)",
                "Budesonid/formoterol",
                code="R03AK07",
                code_system="ATC",
                strength="160/4,5 mikrog",
                form="inh",
                dose=daily("1 puff x 2", "1", "puff", "2"),
            ),
            med(
                "Salbutamol 0,1 mg/dos inh 1-2 doser vid behov",
                "Salbutamol",
                strength="0,1 mg/dos",
                form="inh",
                dose=dosage("1-2 doser vid behov", unit="doser", prn=True),
            ),
            med(
                "Mesalazin 500 mg tabl 1 x 3",
                "Mesalazin",
                strength="500 mg",
                form="tabl",
                dose=daily("1 x 3", "1", "tabl", "3"),
            ),
            med(
                "Järn 100 mg tabl 1 x 1",
                "Järn",
                strength="100 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Folsyra 0,4 mg tabl 1 x 1 (ATC B03BB01)",
                "Folsyra",
                code="B03BB01",
                code_system="ATC",
                strength="0,4 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "D-vitamin 20 mikrog tabl 1 x 1 (ATC A11CC05)",
                "D-vitamin",
                code="A11CC05",
                code_system="ATC",
                strength="20 mikrog",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Kalcium 500 mg tabl 1 x 1 (ATC A12AA04)",
                "Kalcium",
                code="A12AA04",
                code_system="ATC",
                strength="500 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
        ),
        found(
            cond("Z32.1 Graviditet bekräftad (v 9+0)", "Graviditet bekräftad", code="Z32.1", note="v 9+0"),
            cond("J45.9 Astma", "Astma", code="J45.9"),
            cond(
                "K51.9 Ulcerös kolit, diagnostiserad 2019",
                "Ulcerös kolit",
                code="K51.9",
                verification="confirmed",
                onset="2019",
            ),
            cond("D50.9 Järnbristanemi", "Järnbristanemi", code="D50.9"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# en08: antenatal booking in English, congenital heart defect + SVT, drug-scoped NKDA + peanut
# ---------------------------------------------------------------------------------------------

H_EN08 = hetu("1992-02-09", 906)
EN08_DOC = f"""KUVITTEELA ANTENATAL CLINIC / Maternity services
SYNTHETIC TEST DOCUMENT - NOT A REAL PATIENT

ANTENATAL BOOKING NOTE

Patient: WHITFIELD-TEST, Emma Louise
Personal identity code: {H_EN08}
DOB: 09.02.1992
Sex: F
Date: 08.10.2026

PREGNANCY
Last menstrual period 25.08.2026, estimated due date 01.06.2027. Second pregnancy, one previous delivery (caesarean section 2022). No miscarriages.
Height 169 cm, pre-pregnancy weight 66 kg. Non-smoker, no alcohol.
Immunisations: MMR x 2, varicella immune, influenza vaccine 10/2026, COVID-19 booster 2025.
Emergency contact: Oliver Example-Test (partner), phone 040 000 0004.

VITAL SIGNS AND RESULTS
BP 112/68 mmHg, pulse 70/min (08.10.2026).
Hb 124 g/l, rubella IgG positive, HIV and hepatitis B screening negative (06.10.2026).

ALERT
Peanut anaphylaxis: carries adrenaline auto-injector. Cardiology review before delivery.

DIAGNOSES
Z32.1 Pregnancy confirmed (6+2 weeks)
Q21.1 Atrial septal defect, closed 2004
I47.1 Supraventricular tachycardia

MEDICATION
- Metoprolol 50 mg tabl 1 BID (ATC C07AB02)
- Folic acid 0.4 mg tabl 1 OD (ATC B03BB01)
- Vitamin D3 20 mcg tabl 1 OD (ATC A11CC05)
- Calcium carbonate 500 mg tabl 1 OD (ATC A12AA04)
- Pregnancy multivitamin tabl 1 OD
- EpiPen 300 mcg auto-injector, use in anaphylaxis

ALLERGIES
No known drug allergies.
Peanut allergy (anaphylaxis)

PLAN
Shared care with cardiology: ECG at 20 weeks, growth scan at 32 weeks, elective caesarean section to be discussed.

Midwife Test
"""

EN08 = Case(
    case_id="en08_antenatal_booking_chd_txt",
    language="en",
    fmt="txt",
    doc_type="outpatient_note",
    features=(
        MATERNITY,
        NON_SCHEMA,
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "as_needed_dosing",
        "procedure_distractor",
        "nkda_plus_food_allergy",
        "allergy_reactions",
        "abbreviations",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "English antenatal booking note. Also carries dated vaccinations, vital signs, lab "
        "results, an alert and a plan of care (context only; the alert is not a problem). The atrial septal defect Q21 is the 'heart defect' option "
        "and SVT I47 the heart-disease option; the closure is part of the diagnosis line, and the "
        "caesarean is a procedure, not a problem. Supplements: folic acid, vitamin D, calcium, "
        "multivitamin. 'No known drug allergies.' (scope medication) stands next to a peanut "
        "allergy; the EpiPen, used only on a stated trigger (anaphylaxis), is as_needed (sv01 "
        "convention)."
    ),
    document=EN08_DOC,
    gold=extraction(
        "en",
        patient(
            names=[
                name("WHITFIELD-TEST, Emma Louise", family="WHITFIELD-TEST", given=["Emma", "Louise"])
            ],
            birth_date=birth("DOB: 09.02.1992", "1992-02-09"),
            gender=gender("Sex: F", "female"),
            identifiers=[
                ident(f"Personal identity code: {H_EN08}", H_EN08, "Personal identity code")
            ],
        ),
        allergies_found(
            [
                allergy(
                    "Peanut allergy (anaphylaxis)",
                    "Peanut",
                    type="allergy",
                    category="food",
                    reactions=[reaction("anaphylaxis")],
                )
            ],
            [nka_statement("No known drug allergies.", "medication")],
        ),
        found(
            med(
                "Metoprolol 50 mg tabl 1 BID (ATC C07AB02)",
                "Metoprolol",
                code="C07AB02",
                code_system="ATC",
                strength="50 mg",
                form="tabl",
                dose=daily("1 BID", "1", "tabl", "2"),
            ),
            med(
                "Folic acid 0.4 mg tabl 1 OD (ATC B03BB01)",
                "Folic acid",
                code="B03BB01",
                code_system="ATC",
                strength="0.4 mg",
                form="tabl",
                dose=daily("1 OD", "1", "tabl", "1"),
            ),
            med(
                "Vitamin D3 20 mcg tabl 1 OD (ATC A11CC05)",
                "Vitamin D3",
                code="A11CC05",
                code_system="ATC",
                strength="20 mcg",
                form="tabl",
                dose=daily("1 OD", "1", "tabl", "1"),
            ),
            med(
                "Calcium carbonate 500 mg tabl 1 OD (ATC A12AA04)",
                "Calcium carbonate",
                code="A12AA04",
                code_system="ATC",
                strength="500 mg",
                form="tabl",
                dose=daily("1 OD", "1", "tabl", "1"),
            ),
            med(
                "Pregnancy multivitamin tabl 1 OD",
                "Pregnancy multivitamin",
                form="tabl",
                dose=daily("1 OD", "1", "tabl", "1"),
            ),
            med(
                "EpiPen 300 mcg auto-injector, use in anaphylaxis",
                "EpiPen",
                strength="300 mcg",
                form="auto-injector",
                dose=dosage("use in anaphylaxis", prn=True),
            ),
        ),
        found(
            cond(
                "Z32.1 Pregnancy confirmed (6+2 weeks)",
                "Pregnancy confirmed",
                code="Z32.1",
                note="6+2 weeks",
            ),
            cond(
                "Q21.1 Atrial septal defect, closed 2004",
                "Atrial septal defect",
                code="Q21.1",
                note="closed 2004",
            ),
            cond("I47.1 Supraventricular tachycardia", "Supraventricular tachycardia", code="I47.1"),
        ),
    ),
)

# ---------------------------------------------------------------------------------------------
# fi19: one summary for maternity, physiotherapy and unplanned care; severe penicillin allergy
# ---------------------------------------------------------------------------------------------

H19 = hetu("1994-04-18", 913)
FI19_DOC = f"""KUVITTEELAN TERVEYSASEMA / Potilaskooste
SYNTEETTINEN TESTIASIAKIRJA - EI OIKEA POTILAS

POTILASKOOSTE
Koottu äitiysneuvolaa, fysioterapiaa ja päivystystä varten.

Potilas: AHONEN-TESTI, Kaisa Johanna
Henkilötunnus: {H19}
Syntymäaika: 18.04.1994
Sukupuoli: nainen
Äidinkieli: suomi
Koontipäivä: 12.10.2026

HUOMIO
Vaikea lääkeaineyliherkkyys, katso ALLERGIAT. Adrenaliinikynä mukana.

RASKAUS
Raskausviikko 24+1 (12.10.2026). Viimeisten kuukautisten alkamispäivä 26.04.2026, lasketun ajan arvio 31.01.2027. Raskaus 2, synnytyksiä 1 (alateitse 2023, lapsi 3 380 g). Ei keskenmenoja.

MITAT JA ELINTAVAT
Pituus 168 cm, paino ennen raskautta 62 kg, nyt 70 kg. Ei tupakoi. Ei alkoholia. Työ: sairaanhoitaja, päivävuoro.

MITTAUKSET JA TULOKSET
Verenpaine 114/70 mmHg, pulssi 84/min, lämpö 36,8 °C, SpO2 98 % huoneilmassa (12.10.2026).
Veriryhmä A Rh(D) positiivinen. Hb 112 g/l, CRP 3 mg/l, TSH 1,9 mU/l (05.10.2026).

ROKOTUKSET
MPR-rokote 1996 ja 2001, influenssarokote 10/2026, DTaP-rokote 2023. Vesirokko sairastettu.

LAITTEET JA APUVÄLINEET
Inhalaatiovälikammio (Volumatic).

TOIMINTAKYKY
Työkykyinen. Nostaminen ja pitkä seisominen ovat vaikeita selkäkivun vuoksi. Kävelee itsenäisesti 3 km.

TOIMENPITEET
Umpilisäkkeen poisto 2010.

YHTEYSHENKILÖ
Teemu Ahonen-Testi (puoliso), puh. 040 000 0005.

DIAGNOOSIT
Z32.1 Raskaus todettu (rv 24+1)
M54.5 Alaselkäkipu, alkanut syyskuussa 2026
J45.9 Astma
E03.9 Kilpirauhasen vajaatoiminta
N10 Äkillinen pyelonefriitti 2024, parantunut

LÄÄKITYS
- Levotyroksiini 75 mikrog tabl 1 x 1 aamulla (ATC H03AA01)
- Budesonidi/formoteroli 160/4,5 mikrog inh 1 annos x 2 (ATC R03AK07)
- Salbutamoli 0,1 mg/annos inh 1-2 annosta tarv.
- Foolihappo 0,4 mg tabl 1 x 1 (ATC B03BB01)
- Kolekalsiferoli 20 mikrog tabl 1 x 1 (ATC A11CC05)
- Rauta 100 mg tabl 1 x 1
- Parasetamoli 500 mg tabl 1-2 tarv., max 3 x vrk
- EpiPen 300 mikrog adrenaliinikynä, käytetään anafylaksiassa

LOPETETUT LÄÄKKEET
- Ibuprofeeni 400 mg, lopetettu 04/2026 raskauden vuoksi

ALLERGIAT
Penisilliiniallergia (vaikea lääkeaineyliherkkyys): anafylaksia 2015, kriittisyys korkea
Ei muita tiedossa olevia allergioita.

SUUNNITELMA
Äitiysneuvolakäynnit 4 viikon välein. Fysioterapia selkäkipuun 6 käyntiä raskaudenaikaisella ohjelmalla. Päivystyskäynnillä: huomioi allergiatiedot ennen antibioottihoitoa, vältä tulehduskipulääkkeitä ja ilmoita raskaus kuvantamisessa.

Testi Terveydenhoitaja
"""

FI19 = Case(
    case_id="fi19_summary_multi_context_txt",
    language="fi",
    fmt="txt",
    doc_type="outpatient_note",
    features=(
        MATERNITY,
        PHYSIO,
        NON_SCHEMA,
        "multi_context_candidate",
        "severe_allergy_criticality",
        "caps_headings",
        "printed_icd10",
        "printed_atc",
        "resolved_condition",
        "stopped_medication",
        "as_needed_dosing",
        "partial_dates",
        "decimal_comma",
        "procedure_distractor",
        "allergy_reactions",
        "gender_stated",
        "birth_date_stated",
    ),
    notes=(
        "One patient summary built to serve the maternity pre-visit form (pregnancy at 24+1 weeks, "
        "asthma J45, thyroid E03, supplements), the physiotherapy low-back form (M54.5 with onset, "
        "asthma, thyroid, height, weight, smoking) and unplanned care (severe allergy first, "
        "adrenaline pen, stopped NSAID, past pyelonephritis, blood group, vital signs, plan with an "
        "emergency paragraph). The penicillin entry is worded 'vaikea lääkeaineyliherkkyys' "
        "(reaction severity severe), 'anafylaksia' (the reaction) and 'kriittisyys korkea' "
        "(criticality high); the HUOMIO line repeats the hypersensitivity without the substance, so "
        "the allergy is reported once, from the ALLERGIAT line. 'Ei muita tiedossa olevia "
        "allergioita' only confirms the list and is not recorded. Results, vital signs, vaccinations, "
        "devices, the appendectomy, functional status, the contact person and the plan are context "
        "(not in the schema)."
    ),
    document=FI19_DOC,
    gold=extraction(
        "fi",
        patient(
            names=[
                name("AHONEN-TESTI, Kaisa Johanna", family="AHONEN-TESTI", given=["Kaisa", "Johanna"])
            ],
            birth_date=birth("Syntymäaika: 18.04.1994", "1994-04-18"),
            gender=gender("Sukupuoli: nainen", "female"),
            identifiers=[ident(f"Henkilötunnus: {H19}", H19, "Henkilötunnus")],
        ),
        allergies_found(
            [
                allergy(
                    "Penisilliiniallergia (vaikea lääkeaineyliherkkyys): anafylaksia 2015, kriittisyys korkea",
                    "Penisilliini",
                    type="allergy",
                    category="medication",
                    criticality="high",
                    onset="2015",
                    reactions=[reaction("anafylaksia", severity="severe")],
                )
            ]
        ),
        found(
            med(
                "Levotyroksiini 75 mikrog tabl 1 x 1 aamulla (ATC H03AA01)",
                "Levotyroksiini",
                code="H03AA01",
                code_system="ATC",
                strength="75 mikrog",
                form="tabl",
                dose=daily("1 x 1 aamulla", "1", "tabl", "1"),
            ),
            med(
                "Budesonidi/formoteroli 160/4,5 mikrog inh 1 annos x 2 (ATC R03AK07)",
                "Budesonidi/formoteroli",
                code="R03AK07",
                code_system="ATC",
                strength="160/4,5 mikrog",
                form="inh",
                dose=daily("1 annos x 2", "1", "annos", "2"),
            ),
            med(
                "Salbutamoli 0,1 mg/annos inh 1-2 annosta tarv.",
                "Salbutamoli",
                strength="0,1 mg/annos",
                form="inh",
                dose=dosage("1-2 annosta tarv.", unit="annosta", prn=True),
            ),
            med(
                "Foolihappo 0,4 mg tabl 1 x 1 (ATC B03BB01)",
                "Foolihappo",
                code="B03BB01",
                code_system="ATC",
                strength="0,4 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Kolekalsiferoli 20 mikrog tabl 1 x 1 (ATC A11CC05)",
                "Kolekalsiferoli",
                code="A11CC05",
                code_system="ATC",
                strength="20 mikrog",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Rauta 100 mg tabl 1 x 1",
                "Rauta",
                strength="100 mg",
                form="tabl",
                dose=daily("1 x 1", "1", "tabl", "1"),
            ),
            med(
                "Parasetamoli 500 mg tabl 1-2 tarv., max 3 x vrk",
                "Parasetamoli",
                strength="500 mg",
                form="tabl",
                dose=dosage("1-2 tarv., max 3 x vrk", unit="tabl", prn=True),
            ),
            med(
                "EpiPen 300 mikrog adrenaliinikynä, käytetään anafylaksiassa",
                "EpiPen",
                strength="300 mikrog",
                form="adrenaliinikynä",
                dose=dosage("käytetään anafylaksiassa", prn=True),
            ),
            med(
                "Ibuprofeeni 400 mg, lopetettu 04/2026 raskauden vuoksi",
                "Ibuprofeeni",
                strength="400 mg",
                status="stopped",
                end="2026-04",
                note="raskauden vuoksi",
            ),
        ),
        found(
            cond("Z32.1 Raskaus todettu (rv 24+1)", "Raskaus todettu", code="Z32.1", note="rv 24+1"),
            cond(
                "M54.5 Alaselkäkipu, alkanut syyskuussa 2026",
                "Alaselkäkipu",
                code="M54.5",
                onset="2026-09",
            ),
            cond("J45.9 Astma", "Astma", code="J45.9"),
            cond("E03.9 Kilpirauhasen vajaatoiminta", "Kilpirauhasen vajaatoiminta", code="E03.9"),
            cond(
                "N10 Äkillinen pyelonefriitti 2024, parantunut",
                "Äkillinen pyelonefriitti",
                code="N10",
                status="resolved",
                onset="2024",
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------------------------
# Optional sections (schema 1.2.0): vital signs, social history, immunizations, pregnancy,
# patient contacts. Annotated for every case of this module (``extra_sections=True``).
# A vital sign takes the date that stands after its block of measurements ("(06.10.2026)");
# Height and weight with no date of their own are undated. "Ei tupakoi" / "Non-smoker" is
# ``non_smoker`` (not ``never``). One immunization per dose ("MPR-rokote 1997 ja 2002" = two).
# Pregnancy counts are the numbers as written; a qualifier such as "aiemmat" goes to the note.
# ---------------------------------------------------------------------------------------------


def _annotate(
    case: Case,
    *,
    vital_signs: list[dict[str, Any]],
    social_history: list[dict[str, Any]],
    immunizations: list[dict[str, Any]] | None = None,
    pregnancy: list[dict[str, Any]] | None = None,
    contacts: list[dict[str, Any]] | None = None,
    doc_date: dict[str, Any] | None = None,
) -> Case:
    gold = dict(case.gold)
    gold["document_date"] = doc_date
    gold["vital_signs"] = vital_signs
    gold["social_history"] = social_history
    gold["immunizations"] = immunizations or []
    gold["pregnancy"] = pregnancy or []
    gold["patient"] = {**case.gold["patient"], "contacts": contacts or []}
    return replace(case, gold=gold, extra_sections=True)


def _bp_line(quote: str, date: str, *, systolic: str, diastolic: str, pulse: str, unit: str = "/min") -> list[dict[str, Any]]:
    """Blood pressure and pulse that share one dated line."""
    return [
        vital(quote, "blood_pressure", systolic, diastolic=diastolic, unit="mmHg", effective=date),
        vital(quote, "heart_rate", pulse, unit=unit, effective=date),
    ]


_FI13_BLOCK = "Verenpaine 138/84 mmHg, pulssi 72/min, painoindeksi 29,7 (06.10.2026)"
FI13 = _annotate(
    FI13,
    doc_date=document_date("Lähetepäivä: 06.10.2026", "2026-10-06"),
    vital_signs=[
        vital("Pituus 178 cm", "height", "178", unit="cm"),
        vital("paino 94 kg", "weight", "94", unit="kg"),
        *_bp_line(_FI13_BLOCK, "2026-10-06", systolic="138", diastolic="84", pulse="72"),
        vital(_FI13_BLOCK, "body_mass_index", "29.7", effective="2026-10-06"),
    ],
    social_history=[
        social("Ei tupakoi", "tobacco", "Ei tupakoi", tobacco_status="non_smoker"),
        social("Alkoholia käyttää vähän", "alcohol", "Alkoholia käyttää vähän"),
    ],
)

_FI14_BLOCK = "Verenpaine 122/78 mmHg, pulssi 68/min (02.10.2026)"
FI14 = _annotate(
    FI14,
    doc_date=document_date("Käyntipäivä: 02.10.2026", "2026-10-02"),
    vital_signs=[
        vital("Pituus 164 cm", "height", "164", unit="cm"),
        vital("paino 71 kg", "weight", "71", unit="kg"),
        *_bp_line(_FI14_BLOCK, "2026-10-02", systolic="122", diastolic="78", pulse="68"),
    ],
    social_history=[
        social(
            "Tupakoi noin 5 savuketta päivässä",
            "tobacco",
            "Tupakoi noin 5 savuketta päivässä",
            tobacco_status="current",
        ),
    ],
)

_FI15_BLOCK = "Verenpaine 146/88 mmHg, pulssi 78/min, SpO2 93 % huoneilmassa (05.10.2026)"
FI15 = _annotate(
    FI15,
    vital_signs=[
        vital("Pituus 175 cm", "height", "175", unit="cm"),
        vital("paino 88,5 kg", "weight", "88.5", unit="kg"),
        *_bp_line(_FI15_BLOCK, "2026-10-05", systolic="146", diastolic="88", pulse="78"),
        vital(_FI15_BLOCK, "oxygen_saturation", "93", unit="%", effective="2026-10-05"),
    ],
    social_history=[
        social(
            "Tupakointi lopetettu 2019, aiemmin noin 30 askivuotta",
            "tobacco",
            "Tupakointi lopetettu 2019, aiemmin noin 30 askivuotta",
            tobacco_status="former",
            date="2019",
        ),
        social("Alkoholia ei käytä", "alcohol", "Alkoholia ei käytä"),
    ],
)

_SV07_BLOCK = "Blodtryck 126/80 mmHg, puls 70/min, BMI 29,0 (05.10.2026)"
SV07 = _annotate(
    SV07,
    doc_date=document_date("Remissdatum: 05.10.2026", "2026-10-05"),
    vital_signs=[
        vital("Längd 168 cm", "height", "168", unit="cm"),
        vital("vikt 82 kg", "weight", "82", unit="kg"),
        *_bp_line(_SV07_BLOCK, "2026-10-05", systolic="126", diastolic="80", pulse="70"),
        vital(_SV07_BLOCK, "body_mass_index", "29.0", effective="2026-10-05"),
    ],
    social_history=[social("Röker inte", "tobacco", "Röker inte", tobacco_status="non_smoker")],
    immunizations=[
        vaccine("dTp-vaccin 2019", "dTp-vaccin", occurrence="2019"),
        vaccine("influensavaccin 10/2025", "influensavaccin", occurrence="2025-10"),
        vaccine("covid-19-vaccin 2024", "covid-19-vaccin", occurrence="2024"),
    ],
)

_EN07_BLOCK = "BP 124/78 mmHg, pulse 66/min, BMI 23.6 (07.10.2026)"
EN07 = _annotate(
    EN07,
    doc_date=document_date("Date: 07.10.2026", "2026-10-07"),
    vital_signs=[
        vital("Height 183 cm", "height", "183", unit="cm"),
        vital("weight 79 kg", "weight", "79", unit="kg"),
        *_bp_line(_EN07_BLOCK, "2026-10-07", systolic="124", diastolic="78", pulse="66"),
        vital(_EN07_BLOCK, "body_mass_index", "23.6", effective="2026-10-07"),
    ],
    social_history=[social("Non-smoker", "tobacco", "Non-smoker", tobacco_status="non_smoker")],
    immunizations=[
        vaccine("tetanus booster 2021", "tetanus booster", occurrence="2021"),
        vaccine("influenza vaccine 10/2025", "influenza vaccine", occurrence="2025-10"),
    ],
)

_FI16_BLOCK = "Verenpaine 118/72 mmHg, pulssi 76/min (08.10.2026)"
FI16 = _annotate(
    FI16,
    doc_date=document_date("Lähetepäivä: 08.10.2026", "2026-10-08"),
    vital_signs=[
        vital("Pituus 166 cm", "height", "166", unit="cm"),
        vital("paino ennen raskautta 64 kg", "pre_pregnancy_weight", "64", unit="kg"),
        *_bp_line(_FI16_BLOCK, "2026-10-08", systolic="118", diastolic="72", pulse="76"),
    ],
    social_history=[],
    immunizations=[
        vaccine("MPR-rokote 1997 ja 2002", "MPR-rokote", occurrence="1997"),
        vaccine("MPR-rokote 1997 ja 2002", "MPR-rokote", occurrence="2002"),
    ],
    pregnancy=[
        pregnancy_fact(
            "Positiivinen raskaustesti 29.09.2026", "status", status="pregnant", date="2026-09-29"
        ),
        pregnancy_fact(
            "Viimeisten kuukautisten alkamispäivä 11.08.2026",
            "last_menstrual_period",
            date="2026-08-11",
        ),
        pregnancy_fact("lasketun ajan arvio 18.05.2027", "expected_delivery_date", date="2027-05-18"),
        pregnancy_fact("Aiemmat raskaudet: 1", "pregnancies", count="1", note="aiemmat"),
        pregnancy_fact("synnytyksiä 1", "deliveries", count="1"),
    ],
    contacts=[
        contact(
            "Jukka Heinonen-Testi (puoliso), puh. 040 000 0000",
            "Jukka Heinonen-Testi",
            relationship="puoliso",
            phone="040 000 0000",
        )
    ],
)

_FI17_BLOCK = "Verenpaine 128/82 mmHg, pulssi 82/min (08.10.2026)"
FI17 = _annotate(
    FI17,
    doc_date=document_date("Käyntipäivä: 08.10.2026", "2026-10-08"),
    vital_signs=[
        vital("Pituus 171 cm", "height", "171", unit="cm"),
        vital("paino ennen raskautta 78 kg", "pre_pregnancy_weight", "78", unit="kg"),
        *_bp_line(_FI17_BLOCK, "2026-10-08", systolic="128", diastolic="82", pulse="82"),
    ],
    social_history=[social("Ei tupakoi", "tobacco", "Ei tupakoi", tobacco_status="non_smoker")],
    immunizations=[
        vaccine("MPR-rokote kahdesti", "MPR-rokote"),
        vaccine("MPR-rokote kahdesti", "MPR-rokote"),
        vaccine("vesirokkorokote 2012", "vesirokkorokote", occurrence="2012"),
    ],
    pregnancy=[
        pregnancy_fact("Raskaus 3", "pregnancies", count="3"),
        pregnancy_fact("synnytyksiä 2", "deliveries", count="2"),
        pregnancy_fact(
            "Viimeisten kuukautisten alkamispäivä 02.09.2026",
            "last_menstrual_period",
            date="2026-09-02",
        ),
        pregnancy_fact("lasketun ajan arvio 09.06.2027", "expected_delivery_date", date="2027-06-09"),
        pregnancy_fact("Raskaus todettu (rv 5+1)", "status", status="pregnant"),
    ],
    contacts=[
        contact(
            "Mika Esimerkki-Testi (aviomies), puh. 040 000 0001",
            "Mika Esimerkki-Testi",
            relationship="aviomies",
            phone="040 000 0001",
        )
    ],
)

_FI18_BLOCK = "Verenpaine 110/68 mmHg, pulssi 80/min (08.10.2026)"
FI18 = _annotate(
    FI18,
    doc_date=document_date("Käyntipäivä: 08.10.2026", "2026-10-08"),
    vital_signs=[
        vital("Pituus 169 cm", "height", "169", unit="cm"),
        vital("paino ennen raskautta 59 kg", "pre_pregnancy_weight", "59", unit="kg"),
        *_bp_line(_FI18_BLOCK, "2026-10-08", systolic="110", diastolic="68", pulse="80"),
    ],
    social_history=[
        social("Ei tupakoi", "tobacco", "Ei tupakoi", tobacco_status="non_smoker"),
        social("Ei alkoholia", "alcohol", "Ei alkoholia"),
    ],
    immunizations=[
        vaccine("MPR-rokote 2000 ja 2004", "MPR-rokote", occurrence="2000"),
        vaccine("MPR-rokote 2000 ja 2004", "MPR-rokote", occurrence="2004"),
        vaccine("influenssarokote 10/2026", "influenssarokote", occurrence="2026-10"),
        vaccine("koronarokote 2023", "koronarokote", occurrence="2023"),
    ],
    pregnancy=[
        pregnancy_fact(
            "Viimeisten kuukautisten alkamispäivä 19.07.2026",
            "last_menstrual_period",
            date="2026-07-19",
        ),
        pregnancy_fact("laskettu aika 25.04.2027", "expected_delivery_date", date="2027-04-25"),
        pregnancy_fact("Raskaus todettu (rv 11+4)", "status", status="pregnant"),
    ],
    contacts=[
        contact(
            "Aaro Nieminen-Testi (puoliso), puh. 040 000 0002",
            "Aaro Nieminen-Testi",
            relationship="puoliso",
            phone="040 000 0002",
        )
    ],
)

_SV08_BLOCK = "Blodtryck 112/70 mmHg, puls 74/min (08.10.2026)"
SV08 = _annotate(
    SV08,
    doc_date=document_date("Remissdatum: 08.10.2026", "2026-10-08"),
    vital_signs=[
        vital("Längd 172 cm", "height", "172", unit="cm"),
        vital("vikt före graviditeten 66 kg", "pre_pregnancy_weight", "66", unit="kg"),
        *_bp_line(_SV08_BLOCK, "2026-10-08", systolic="112", diastolic="70", pulse="74"),
    ],
    social_history=[social("Röker inte", "tobacco", "Röker inte", tobacco_status="non_smoker")],
    immunizations=[
        vaccine("MPR-vaccin 1995 och 2000", "MPR-vaccin", occurrence="1995"),
        vaccine("MPR-vaccin 1995 och 2000", "MPR-vaccin", occurrence="2000"),
    ],
    pregnancy=[
        pregnancy_fact(
            "Positivt graviditetstest 03.10.2026", "status", status="pregnant", date="2026-10-03"
        ),
        pregnancy_fact(
            "Första dagen av sista menstruationen 06.08.2026",
            "last_menstrual_period",
            date="2026-08-06",
        ),
        pregnancy_fact("beräknad förlossning 13.05.2027", "expected_delivery_date", date="2027-05-13"),
        pregnancy_fact("Tidigare graviditeter: 0", "pregnancies", count="0", note="tidigare"),
    ],
    contacts=[
        contact(
            "Erik Exempel-Test (make), tel 040 000 0003",
            "Erik Exempel-Test",
            relationship="make",
            phone="040 000 0003",
        )
    ],
)

_EN08_BLOCK = "BP 112/68 mmHg, pulse 70/min (08.10.2026)"
EN08 = _annotate(
    EN08,
    doc_date=document_date("Date: 08.10.2026", "2026-10-08"),
    vital_signs=[
        vital("Height 169 cm", "height", "169", unit="cm"),
        vital("pre-pregnancy weight 66 kg", "pre_pregnancy_weight", "66", unit="kg"),
        *_bp_line(_EN08_BLOCK, "2026-10-08", systolic="112", diastolic="68", pulse="70"),
    ],
    social_history=[
        social("Non-smoker", "tobacco", "Non-smoker", tobacco_status="non_smoker"),
        social("no alcohol", "alcohol", "no alcohol"),
    ],
    immunizations=[
        vaccine("MMR x 2", "MMR"),
        vaccine("MMR x 2", "MMR"),
        vaccine("influenza vaccine 10/2026", "influenza vaccine", occurrence="2026-10"),
        vaccine("COVID-19 booster 2025", "COVID-19 booster", occurrence="2025"),
    ],
    pregnancy=[
        pregnancy_fact(
            "Last menstrual period 25.08.2026", "last_menstrual_period", date="2026-08-25"
        ),
        pregnancy_fact("estimated due date 01.06.2027", "expected_delivery_date", date="2027-06-01"),
        pregnancy_fact("Second pregnancy", "pregnancies", count="2"),
        pregnancy_fact("one previous delivery", "deliveries", count="1", note="previous"),
        pregnancy_fact("Pregnancy confirmed (6+2 weeks)", "status", status="pregnant"),
    ],
    contacts=[
        contact(
            "Oliver Example-Test (partner), phone 040 000 0004",
            "Oliver Example-Test",
            relationship="partner",
            phone="040 000 0004",
        )
    ],
)

_FI19_BLOCK = (
    "Verenpaine 114/70 mmHg, pulssi 84/min, lämpö 36,8 °C, SpO2 98 % huoneilmassa (12.10.2026)"
)
FI19 = _annotate(
    FI19,
    doc_date=document_date("Koontipäivä: 12.10.2026", "2026-10-12"),
    vital_signs=[
        vital("Pituus 168 cm", "height", "168", unit="cm"),
        vital("paino ennen raskautta 62 kg", "pre_pregnancy_weight", "62", unit="kg"),
        vital("nyt 70 kg", "weight", "70", unit="kg"),
        *_bp_line(_FI19_BLOCK, "2026-10-12", systolic="114", diastolic="70", pulse="84"),
        vital(_FI19_BLOCK, "body_temperature", "36.8", unit="°C", effective="2026-10-12"),
        vital(_FI19_BLOCK, "oxygen_saturation", "98", unit="%", effective="2026-10-12"),
    ],
    social_history=[
        social("Ei tupakoi", "tobacco", "Ei tupakoi", tobacco_status="non_smoker"),
        social("Ei alkoholia", "alcohol", "Ei alkoholia"),
    ],
    immunizations=[
        vaccine("MPR-rokote 1996 ja 2001", "MPR-rokote", occurrence="1996"),
        vaccine("MPR-rokote 1996 ja 2001", "MPR-rokote", occurrence="2001"),
        vaccine("influenssarokote 10/2026", "influenssarokote", occurrence="2026-10"),
        vaccine("DTaP-rokote 2023", "DTaP-rokote", occurrence="2023"),
    ],
    pregnancy=[
        pregnancy_fact(
            "Raskausviikko 24+1 (12.10.2026)", "status", status="pregnant", date="2026-10-12"
        ),
        pregnancy_fact(
            "Viimeisten kuukautisten alkamispäivä 26.04.2026",
            "last_menstrual_period",
            date="2026-04-26",
        ),
        pregnancy_fact("lasketun ajan arvio 31.01.2027", "expected_delivery_date", date="2027-01-31"),
        pregnancy_fact("Raskaus 2", "pregnancies", count="2"),
        pregnancy_fact("synnytyksiä 1", "deliveries", count="1"),
    ],
    contacts=[
        contact(
            "Teemu Ahonen-Testi (puoliso), puh. 040 000 0005",
            "Teemu Ahonen-Testi",
            relationship="puoliso",
            phone="040 000 0005",
        )
    ],
)


# ---------------------------------------------------------------------------------------------
# Results, procedures, devices (schema 1.4.0). Added to the gold of every case of this module.
# A result takes the date that stands after its block of results ("(24.09.2026)"), like a vital
# sign; the quote is the result itself. Laboratory results are `laboratory`; spirometry and bone
# density are `other`. A negative number or a text result is `value_text`. A delivery in the
# pregnancy history and a closure inside a diagnosis line are not procedures.
# ---------------------------------------------------------------------------------------------

EXTRAS_1_4: dict[str, dict[str, list[dict[str, Any]]]] = {
    "fi13_referral_physio_lbp_txt": {
        "results": [
            result("HbA1c 52 mmol/mol", "HbA1c", value="52", unit="mmol/mol", effective="2026-09-24"),
            result("P-Krea 78 µmol/l", "P-Krea", value="78", unit="µmol/l", effective="2026-09-24"),
            result(
                "LDL-kolesteroli 2,9 mmol/l",
                "LDL-kolesteroli",
                value="2,9",
                unit="mmol/l",
                effective="2026-09-24",
            ),
        ],
    },
    "fi14_outpatient_physio_lbp_txt": {
        "results": [
            result("TSH 2,1 mU/l", "TSH", value="2,1", unit="mU/l", effective="2026-09-22"),
            result(
                "25-OH-D-vitamiini 58 nmol/l",
                "25-OH-D-vitamiini",
                value="58",
                unit="nmol/l",
                effective="2026-09-22",
            ),
            result(
                "Luuntiheysmittaus (DXA) 2023: T-arvo -2,7",
                "Luuntiheysmittaus (DXA)",
                value_text="T-arvo -2,7",
                effective="2023",
                category="other",
            ),
        ],
    },
    "fi15_outpatient_physio_copd_txt": {
        "results": [
            result(
                "Spirometria 09/2026: FEV1 62 % viitearvosta",
                "FEV1",
                value="62",
                unit="% viitearvosta",
                effective="2026-09",
                category="other",
            ),
            result("Hb 148 g/l", "Hb", value="148", unit="g/l", effective="2026-09-28"),
        ],
        "devices": [
            device("Inhalaatiovälikammio (Volumatic)", "Inhalaatiovälikammio", brand="Volumatic"),
            device("kävelykeppi", "kävelykeppi"),
        ],
    },
    "sv07_referral_physio_lbp_txt": {
        "procedures": [procedure("appendektomi 2008", "appendektomi", performed="2008")],
    },
    "en07_referral_physio_lbp_txt": {
        "results": [
            result("HbA1c 58 mmol/mol", "HbA1c", value="58", unit="mmol/mol", effective="2026-09-23"),
            result(
                "eGFR above 90 ml/min",
                "eGFR",
                value="90",
                comparator="gt",
                unit="ml/min",
                effective="2026-09-23",
            ),
        ],
        "devices": [
            device(
                "Continuous glucose monitor (FreeStyle Libre 2)",
                "Continuous glucose monitor",
                brand="FreeStyle Libre 2",
            )
        ],
    },
    "fi16_referral_maternity_t1dm_txt": {
        "results": [
            result("HbA1c 49 mmol/mol", "HbA1c", value="49", unit="mmol/mol", effective="2026-09-29"),
            result("TSH 1,8 mU/l", "TSH", value="1,8", unit="mU/l", effective="2026-09-29"),
        ],
        "devices": [
            device(
                "Jatkuva sokeriseuranta (FreeStyle Libre 2)",
                "Jatkuva sokeriseuranta",
                brand="FreeStyle Libre 2",
            )
        ],
    },
    "fi17_maternity_intake_epilepsy_txt": {
        "results": [
            result(
                "Lamotrigiinipitoisuus 8,2 mg/l",
                "Lamotrigiinipitoisuus",
                value="8,2",
                unit="mg/l",
                effective="2026-10-05",
            ),
            result("Hb 121 g/l", "Hb", value="121", unit="g/l", effective="2026-10-05"),
            result("ferritiini 18 µg/l", "ferritiini", value="18", unit="µg/l", effective="2026-10-05"),
        ],
    },
    "fi18_maternity_intake_crohn_pdf": {
        "results": [
            result("Hb 108 g/l", "Hb", value="108", unit="g/l", effective="2026-10-06"),
            result("ferritiini 9 µg/l", "ferritiini", value="9", unit="µg/l", effective="2026-10-06"),
            result("CRP 4 mg/l", "CRP", value="4", unit="mg/l", effective="2026-10-06"),
        ],
        "procedures": [
            procedure(
                "Suolen osaresektio 2019 Crohnin taudin vuoksi",
                "Suolen osaresektio",
                performed="2019",
                note="Crohnin taudin vuoksi",
            )
        ],
    },
    "sv08_referral_maternity_asthma_txt": {
        "results": [
            result("Hb 118 g/l", "Hb", value="118", unit="g/l", effective="2026-10-05"),
            result("ferritin 14 µg/l", "ferritin", value="14", unit="µg/l", effective="2026-10-05"),
            result(
                "fekalt kalprotektin 45 µg/g",
                "fekalt kalprotektin",
                value="45",
                unit="µg/g",
                effective="2026-10-05",
            ),
        ],
        "procedures": [
            procedure("appendektomi 2008", "appendektomi", performed="2008"),
            procedure("Koloskopi 03/2026", "Koloskopi", performed="2026-03"),
        ],
        "devices": [device("Spacer (Volumatic)", "Spacer", brand="Volumatic")],
    },
    "en08_antenatal_booking_chd_txt": {
        "results": [
            result("Hb 124 g/l", "Hb", value="124", unit="g/l", effective="2026-10-06"),
            result(
                "rubella IgG positive", "rubella IgG", value_text="positive", effective="2026-10-06"
            ),
            result(
                "HIV and hepatitis B screening negative",
                "HIV and hepatitis B screening",
                value_text="negative",
                effective="2026-10-06",
            ),
        ],
    },
    "fi19_summary_multi_context_txt": {
        "results": [
            result(
                "Veriryhmä A Rh(D) positiivinen",
                "Veriryhmä",
                value_text="A Rh(D) positiivinen",
                effective="2026-10-05",
            ),
            result("Hb 112 g/l", "Hb", value="112", unit="g/l", effective="2026-10-05"),
            result("CRP 3 mg/l", "CRP", value="3", unit="mg/l", effective="2026-10-05"),
            result("TSH 1,9 mU/l", "TSH", value="1,9", unit="mU/l", effective="2026-10-05"),
        ],
        "procedures": [
            procedure("Umpilisäkkeen poisto 2010", "Umpilisäkkeen poisto", performed="2010")
        ],
        "devices": [
            device("Inhalaatiovälikammio (Volumatic)", "Inhalaatiovälikammio", brand="Volumatic")
        ],
    },
}

CASES = [
    replace(c, gold={**c.gold, **EXTRAS_1_4[c.case_id]})
    for c in (FI13, FI14, FI15, SV07, EN07, FI16, FI17, FI18, SV08, EN08, FI19)
]
