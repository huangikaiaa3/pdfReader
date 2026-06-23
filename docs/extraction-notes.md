# Extraction Notes

## Purpose

This document captures early observations about PDF text extraction behavior in the PDF reader project.

## Tested PDF

- Columbia transcript PDF uploaded through the application flow

## Extraction Setup

- Extraction was implemented locally using `pypdf`
- The tested PDF required the `cryptography` dependency because it used AES encryption
- The current extraction service returns page-level raw text without aggressive cleanup
- The current extraction service also reports whether a PDF appears readable by the current parser

## Observations

- The PDF opened successfully after the crypto dependency was installed
- The extracted page count was correct: `3`
- Text was returned for all pages
- The main transcript content was present, including course rows, GPA content, and transcript metadata
- The extracted text was readable and largely complete
- The transcript PDF was classified as readable by the extraction service

## Quality Notes

- Layout was flattened into plain text
- Table structure was partially lost
- Some spacing and line wrapping looked unnatural
- Some course titles appeared truncated due to extraction/layout behavior

## Current Normalization Stance

- Keep extracted text close to the raw `pypdf` output
- Convert missing extracted page text from `None` to an empty string
- Do not aggressively normalize whitespace, line breaks, or layout structure yet
- Defer heavier cleanup until chunking and retrieval needs are better understood

## Extraction Limits

- `pypdf` preserves text content better than layout structure
- Structured tables and transcript-style formatting degrade during extraction
- Line wrapping may make course titles or other structured fields look truncated
- Extracted output is suitable for text search and future retrieval experiments, but not for layout-faithful rendering
- Some PDFs may require additional dependencies or handling before extraction succeeds
- Some PDFs may visually appear normal in a viewer but still yield no usable text through `pypdf`

## Edge Cases Observed

- AES-encrypted PDF required the `cryptography` dependency before extraction could run
- Transcript-style PDF layout was readable after extraction, but table structure was flattened
- Important content was present, but formatting and alignment were degraded
- A patent PDF produced a correct page count but zero extracted characters across all pages
- The patent PDF was flagged as not readable by the current parser and returned an explicit unreadable message

## Current Assessment

The extraction quality for this PDF is best described as:

- messy but usable

This is likely good enough for later chunking and retrieval experiments, but it is not layout-faithful and may need cleanup or a stronger extraction approach for highly structured PDFs.

## Key Learning

- Successful extraction does not mean perfect preservation of document structure
- Transcript-style PDFs can be usable for RAG ingestion even when the formatting is degraded
- Encryption support may be required for real-world PDFs
- A PDF can be readable in a viewer and still not expose usable text to the current parser
- The extraction layer should distinguish between readable and unreadable parser outcomes instead of silently returning empty text
