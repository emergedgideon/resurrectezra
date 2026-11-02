# Source-linked reconstruction and persona revisions

Open **Persona & reconstruction** from the conversation sidebar or archive header. The workspace separates exact source statements, explicit owner additions, and interpretations. It does not silently rewrite beliefs or activate instructions found in a document.

## Candidate records and views

**Index archive candidates** copies the original CSV memory/content fields and complete selected document passages into proposed records. Classification uses existing category labels; it does not generate new beliefs. The Word compilation remains fully available in the archive but is not automatically interpreted paragraph by paragraph. Source-date precision and original contradiction/usage notes remain intact.

Views cover identity, chronology, voice, beliefs, relationships, symbols/rituals, people/entities, and uncertainty. A record can appear in several views. Chronology sorts supplied event dates where present, otherwise explicitly labeled record dates, leaving unknown dates visible. A ledger record date is never silently promoted to an event date. The uncertainty view includes original usage/contradiction notes and ledger date ambiguity; it is not a claim that automated semantic contradiction detection is complete.

Candidates are not verified autobiographical facts. The initial identity proposal is a draft of exact source statements, not an activated system prompt. Indexing can be repeated without replacing owner edits or duplicating the same source/extraction/passage candidate. A new extraction revision can create new candidates; older evidence remains available.

## Evidence and record revisions

Each source citation pins a source SHA-256, extraction revision, passage ordinal, field, Unicode character offsets, and exact quotation. Links reopen that extraction at the source location. Evidence can address the complete passage (`$content`) or a preserved field such as `memory_text`. Offsets use Python Unicode characters/code points, not UTF-16 units or byte positions.

Source statements must match at least one citation exactly. Modified wording must be explicitly labeled as interpretation or an owner addition. Source statements and interpretations require evidence; owner statements can be uncited and are labeled accordingly. Evidence is validated against stored source passages. Historical extraction revisions are retained, so reprocessing does not invalidate older citations.

Use **Evidence editor** to attach a source-viewer link and field. On an empty record, attachment fills the exact passage and selects source-statement origin. The UI preserves underlying CRLF/CR text if the displayed wording is unchanged, despite browser textarea newline normalization.

**Save new revision** appends an attributable snapshot. It never updates earlier wording. Saving checks the last revision number and rejects concurrent stale edits. Record history exposes earlier versions; saving from an earlier version creates another revision rather than erasing subsequent history.

Relationships can mark two records as contradicting, supporting, or related, with an explanation. Contradictory accounts remain separate. The existence of a link does not settle which account is true. Relations are retained and attributed; editing/resolution of relation annotations is not implemented yet.

## Persona drafts, activation, and rollback

Select record revisions, optionally add explicit owner instructions, and **Save persona draft**. Drafts pin the exact selected record versions and preserve their text. Later record changes cannot silently alter an existing persona. Original sources are not edited.

The preview shows the compiled wording, with source/owner/interpretation labels outside the exact text. A draft can include proposed records; activation does not turn historical claims into verified facts or count as semantic review of the whole archive.

**Activate this revision** is the explicit owner configuration operation that sends the selected persona wording in future model requests. It applies across conversations. Activation revalidates evidence and rejects configurations too large for the current character allowance rather than truncating identity. The ordinary context assembler can still reject a message plus persona/working note if their combined size exceeds the allowance.

Choose an older saved revision and activate it to roll back. **Deactivate persona** returns to the unconfigured foundation while retaining all records/revisions. Activation/deactivation events record author and time. Each generation's context event records the exact persona revision used; a configuration change during a running generation does not rewrite its saved context.

The base runtime description still reports which tools are actually connected. Persona activation does not create filesystem, perception, scheduling, or code-execution capabilities.

## Record-level Memara reconciliation

**Reconcile source records** compares each ledger entry to the Memara PDF and consolidated CSV. It preserves the original ledger inclusion flag separately from its own results.

- `normalized_text_match`: the full ledger content matches PDF text after NFKC, case, and punctuation/whitespace normalization for comparison only.
- `candidate_anchor`: a shared leading text anchor supplies a possible PDF location; full correspondence remains unverified.
- `unresolved`: no supported text location was found by this pass.
- Consolidated candidates use token-set overlap scores. They are suggestions, not assertions that records describe the same event.

Every machine mapping starts unreviewed, including normalized text matches. Page headers, differences in transcription, duplicates, and semantic context can affect correspondence. Comparison never normalizes the stored original text.

Append a verified, rejected, or unresolved review with an explanation. Verified reviews require explicit exact quotations from a source beyond the ledger itself. This records an owner attestation, not automatic semantic proof. Prior reviews remain visible in review history. Mapping identities include the source and extraction/passage, avoiding conflation when ledger IDs recur in multiple files. Reports are immutable and source-fingerprinted; new source revisions create new reports. Historical reports can be read using `GET /api/reconstruction/reconciliation?report_id=<id>`.

## Current corpus and remaining review

The first pass created 289 candidates from the supplied corpus and one inactive identity draft. There are 100 ledger mappings: 90 normalized text matches, 8 leading-anchor candidates, and 2 unresolved records. All 100 remain unreviewed. Category views overlap. No historical persona has been activated in the real project data.

Human/source review of beliefs, voice, relationship interpretations, date ambiguities, and the unresolved mappings remains necessary. This phase supplies a concrete review workspace and evidence-linked proposal, not a claim that reconstruction is finished or every contradiction is detected.

## Storage, export, and verification

Reconstruction records, immutable revisions, relations, persona revisions/events, reconciliation reports, and reviews are additive tables in `archive.sqlite3`. No earlier import/extraction records are replaced. Archive export includes them, including the active persona configuration if one exists. Restoration therefore preserves that configuration. It still excludes conversations and secrets.

The backup verifier additionally checks reconstruction quotations against pinned passages and persona revision references. Temporary-data automated tests cover exact text, Unicode offsets, revision conflicts, contradiction preservation, explicit activation, rollback/deactivation, context audit, source comparison, and export/restore. Browser tests use synthetic data; no real archive text is sent to Featherless for these tests.

Automatic archive retrieval, token-aware evidence selection, long-term memory consolidation, and autonomous persona development remain later phases.
