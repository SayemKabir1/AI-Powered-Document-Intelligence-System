# AI-Assisted Development and Model Disclosure

## 1. Development Disclosure

The AI-Powered Document Intelligence System was developed through an iterative process involving independent technical work, problem-solving, implementation, testing, debugging, and AI-assisted development.

AI tools were used as development assistants in several areas:

- **Technical guidance:** Exploring software architecture, technology choices, and possible implementation approaches.
- **Code assistance:** Reviewing code, suggesting improvements, and assisting with selected implementation tasks.
- **Debugging and troubleshooting:** Investigating errors, identifying potential issues, and exploring possible solutions.
- **Testing support:** Designing test scenarios, reviewing test coverage, and analyzing test results.
- **Documentation:** Improving technical explanations, setup instructions, and project documentation.
- **Security review:** Identifying potential vulnerabilities and reviewing security-related implementation decisions.

The overall architecture, technical integration, implementation decisions, local execution, testing, and verification were carried out through an iterative development process with human review and validation.

AI-generated suggestions were reviewed and tested before being incorporated into the project. The developer remains responsible for the final source code, implementation decisions, and project functionality.

## 2. Runtime AI Design

The application uses a combination of local AI capabilities and deterministic processing.

- **Optional local LLM:** Ollama with a configurable model (default `qwen2.5:3b`) can extract invoice fields from document text using a JSON-schema-constrained response.
- **Fallback processing:** If Ollama is disabled, unavailable, or fails, a rules-based parser extracts information from explicit labels. Values that cannot be confidently identified are left as `null`.
- **Optional embeddings:** Ollama with `nomic-embed-text` can generate local vectors for semantic or hybrid search. If embeddings are unavailable, search falls back to keyword search and reports the search mode used.
- **Non-generative processing:** PDF text extraction, OCR, spreadsheet parsing, database persistence, and arithmetic validation use deterministic tools and rules rather than an LLM.

The implementation does not require a paid inference service. Local inference uses the computer's available CPU, GPU, and memory.

The saved evaluation results record Ollama-backed extraction for four of five CSV samples and six of seven clean multi-format samples. These results demonstrate the recorded extraction runs but do not guarantee that Ollama or the configured models will be available on another machine.

The embedding workflow should only be demonstrated when it has been verified in the demonstration environment.

## 3. Examples of AI-Assisted Development Tasks

The following are representative examples of how AI assistance was used during development. They are paraphrased examples, not a complete record of the original prompts.

- Exploring an architecture for an AI-powered document processing and invoice extraction system using locally available tools.
- Reviewing extraction logic and identifying potential issues with invoice fields and line items.
- Suggesting test scenarios for financial validation, incorrect values, and document-processing failures.
- Reviewing application code for potential security vulnerabilities and recommending improvements.
- Investigating automated test failures and suggesting regression tests for corrected functionality.

## 4. Human Review and Responsible Use

This system is a document extraction and review aid, not an autonomous accounting or payment approval system.

Extracted information may be incorrect or incomplete. Users should review validation errors and warnings, verify important figures against the original documents, and manually approve high-impact decisions.

The evaluation dataset consists of controlled synthetic examples intended for reproducibility. Its results should not be interpreted as proof of production-level accuracy or reliability.

The developer is responsible for reviewing, maintaining, and verifying the final implementation.
