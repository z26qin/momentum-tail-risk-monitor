# AI value comparison summary

Lightweight worksheet only. Human-review score columns are left blank.

## Already demonstrated

- AI cannot mutate quantitative state (quant_fields_unchanged across runnable arms: True).
- Evidence is timestamp-controlled (automatic `evidence_cutoff_valid` checks on worksheet rows).
- Outputs are schema-constrained (`DeterministicSynthesizer` / `EvidenceInterpretation` contracts).
- Deterministic fallback exists when LLM credentials or an injected interpreter are unavailable.
- External LLM actually called in this regeneration: 0 case(s); `not_run`: 4 case(s).

## To be evaluated

- Whether LLM commentary is more mechanism-specific than the template.
- Whether contradiction coverage improves for analysts.
- Whether analyst review time falls.
- Whether unsupported claims remain acceptably low.

## Conclusion

The repository demonstrates a safe architecture for AI-assisted explanation, while incremental analyst value remains a testable hypothesis.

Do **not** conclude that AI creates incremental PM value until a reviewed external LLM run fills the human-score columns in `ai_value_review.csv`.

Worksheet rows: 12. Artifact: `ai_value_review.csv`.
