"""LUVN clinical database export: per-patient JSON dump and its deterministic parser.

* `dump`: import the LUVN table files into SQLite and write one JSON dump per patient. The dump is
  the tables themselves: ``tables.<table>`` is the list of that patient's rows with the original
  column names, so anyone who knows the table schema recognises it.
* `parse`: read such a dump into the intermediate extraction schema without an LLM.
"""
