# AI-assisted development and model disclosure

## Development disclosure

This project was developed with AI assistance for architecture planning, code drafting, test generation, documentation and security-review prompts. The resulting source code and tests were executed in the available Linux workspace. This disclosure does not imply that all generated code is correct or that the system is production-ready; the limitations documented in the README, evaluation report and security assessment remain applicable.

## Runtime AI design

- **Optional local LLM:** Ollama with a configurable model (default `qwen2.5:3b`) may extract invoice fields from document text using a JSON-schema-constrained response.
- **Fallback:** If Ollama is disabled, unavailable or fails, a rules-based parser extracts fields from explicit labels and leaves values it cannot confidently identify as `null`.
- **Optional embeddings:** Ollama with `nomic-embed-text` may generate local vectors for semantic or hybrid search. If embeddings are unavailable, search falls back to keyword search and reports that mode.
- **Non-generative processing:** PDF text extraction, OCR, spreadsheet parsing, database persistence and arithmetic checks use deterministic tools/rules rather than an LLM.

No paid inference service is required The Ollama-backed inference and embedding paths must be verified on the machine used for theby the implementation. Local inference still uses the computer's CPU/GPU and memory. The saved evaluation results record Ollama-backed extraction for four of five CSV samples and six of seven clean multi-format samples. This verifies those recorded extraction runs, but does not guarantee that Ollama or the configured models will be available on another machine. The embedding workflow should be demonstrated only when it has been verified on the demonstration environment.

## Human review and responsible use

This system is a review aid, not an autonomous accounting or payment approval system. Extracted fields may be wrong or incomplete. Review validation errors and warnings, confirm important figures against the original document, and manually approve high-impact decisions. The small synthetic dataset in `evaluation/` is for reproducibility only and does not demonstrate production accuracy.

# AI-Assisted Development Disclosure

AI tools were used as development assistants during the implementation of the AI-Powered Document Intelligence System.

The development process involved a combination of personal technical work, independent decision-making, testing, debugging, and AI-assisted support.

AI assistance was primarily used for:

- **Technical guidance:** Exploring implementation approaches, software architecture, and technology choices.
- **Code assistance:** Reviewing code, suggesting improvements, and helping implement selected features.
- **Debugging and troubleshooting:** Investigating errors, identifying potential issues, and suggesting possible solutions.
- **Testing support:** Developing test scenarios, reviewing test coverage, and analyzing test results.
- **Documentation:** Improving technical explanations, project documentation, and setup instructions.

The project architecture, integration decisions, implementation, local execution, testing, and verification were carried out through an iterative development process with human review and validation.

AI-generated suggestions were reviewed and tested before being incorporated into the project. AI tools were used to support development, not as a replacement for the developer's understanding, decisions, or responsibility for the final implementation.
