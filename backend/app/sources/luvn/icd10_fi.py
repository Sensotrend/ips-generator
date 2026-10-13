"""Finnish display names for the ICD-10 codes that occur in the LUVN synthetic data.

The ``diagnoosi`` table has only the code. These names (text, **not** codes) make the problem list
readable; the code itself always travels as ``printed_code`` and is coded only if the terminology
server confirms it (PLAN D-9). Names were taken from the visit notes of the same dataset. An
unknown code falls back to ``"ICD-10 <code>"`` in the parser.
"""

from __future__ import annotations

from typing import Final

ICD10_FI: Final[dict[str, str]] = {
    "A09": "Tarttuvaksi oletettu ripuli ja maha-suolitulehdus",
    "E03.9": "Määrittämätön kilpirauhasen vajaatoiminta",
    "E11.9": "Aikuistyypin diabetes ilman komplikaatioita",
    "F32.9": "Määrittämätön masennustila",
    "F41.9": "Määrittämätön ahdistuneisuushäiriö",
    "G47.0": "Nukahtamis- ja unessapysymishäiriöt",
    "H10.3": "Määrittämätön akuutti sidekalvotulehdus",
    "H61.2": "Korvavahatulppa",
    "H66.0": "Akuutti märkäinen välikorvan tulehdus",
    "I10": "Essentiaalinen (primaarinen) hypertensio",
    "J06.9": "Määrittämätön akuutti ylähengitystieinfektio",
    "J30.4": "Määrittämätön allerginen nuha",
    "J45.9": "Määrittämätön astma",
    "K21.9": "Ruokatorven refluksisairaus ilman ruokatorvitulehdusta",
    "K59.0": "Ummetus",
    "L08.9": "Ihon ja ihonalaiskudoksen määrittämätön paikallinen infektio",
    "L30.9": "Määrittämätön ihottuma",
    "M17.9": "Määrittämätön polvinivelrikko",
    "M25.5": "Nivelkipu",
    "M54.2": "Niskakipu",
    "M54.5": "Alaselkäkipu",
    "N30.0": "Akuutti virtsarakkotulehdus",
    "R10.4": "Muu tai määrittämätön vatsakipu",
    "R29.6": "Kaatumistaipumus, muualle luokittamaton",
    "R42": "Huimaus ja pyörrytys",
    "R51": "Päänsärky",
    "S52.5": "Värttinäluun alaosan murtuma",
    "S61.9": "Ranteen ja käden määrittämätön avohaava",
    "S69.9": "Ranteen ja käden määrittämätön vamma",
    "S93.4": "Nilkan nyrjähdys tai venähdys",
}
