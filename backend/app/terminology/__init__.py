"""FHIR terminology server access for pipeline step 5 (PLAN.md §2, D2).

* `app.terminology.scopes` - code systems and search scopes (IPS 2.0.1 bindings, verified
  against tx.fhir.org);
* `app.terminology.client` - typed, cached, rate-limited FHIR terminology client;
* `app.terminology.tools` - tool definitions Claude uses in the coding loop.

The coding step itself (deterministic pass + Claude tool loop) is `app.pipeline.terminology`.
"""
