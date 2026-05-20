# Knowledge Data Versioning

This directory separates source knowledge from generated vector database files.

## Versioned Source Data

`documents/*.txt` files are the canonical source data and should be committed to Git.

Current document groups:

- `01-09`: lifestyle guidance
- `10-19`: ICD-10 disease classification
- `20-29`: clinical guideline snippets

## Generated Artifacts

`milvus_lite.db` is a local generated artifact. It is intentionally ignored by Git and Docker build context.

Regenerate it from source documents:

```bash
medagentcare-import-knowledge
```

For deployment, either run the import step during environment setup or mount a prebuilt database through a volume. Do not commit local `.db` files to the source repository.
