#

# \# Evaluation Report

# \## AI-Powered Document Intelligence System

#

# \## 1. Evaluation Overview

#

# The project was evaluated using controlled synthetic invoice datasets covering CSV, XLSX, XLS, JPG, TIFF, digital PDFs, scanned PDFs, degraded images, corrupted documents and unsupported file formats.

#

# The results below are measurements from the saved evaluation runs. They should not be interpreted as production benchmarks or guarantees of real-world accuracy.

#

# \## 2. Five-Document CSV Evaluation

#

# Dataset: `evaluation/ground\_truth.json`

#

# | Metric | Result |

# |---|---:|

# | Labeled documents | 5 |

# | Successful documents | 5/5 |

# | Document success rate | 100% |

# | Document failure rate | 0% |

# | Overall field exact-match accuracy | 100% |

# | Per-field exact-match accuracy | 100% for all 8 fields |

# | Line-item exact-match rate | 100% |

# | Mean processing time | 9.26884 seconds/document |

# | Median processing time | 8.51815 seconds/document |

# | P95 processing time | 12.0736 seconds/document |

#

# Extraction methods: four documents used Ollama and one used rules-based extraction.

#

# The eight evaluated fields were invoice number, invoice date, supplier name, customer name, subtotal, tax, total and currency.

#

# \## 3. Multi-Format Evaluation

#

# Dataset: `evaluation/multiformat\_ground\_truth.json`

#

# \### 3.1 Clean Samples

#

# Seven clean samples were evaluated across CSV, XLSX, XLS, JPG, TIFF, digital PDF and scanned PDF formats.

#

# | Metric | Result |

# |---|---:|

# | Documents processed successfully | 7/7 |

# | Document success rate | 100% |

# | Overall field exact-match accuracy | 100% |

# | Per-field exact-match accuracy | 100% |

# | Line-item exact-match rate | 100% |

# | Mean processing time | 10.12147 seconds/document |

# | Median processing time | 9.68426 seconds/document |

# | P95 processing time | 12.11664 seconds/document |

#

# Extraction methods: six documents used Ollama and one used rules-based extraction.

#

# \### 3.2 Degraded Samples

#

# Two degraded samples were evaluated, including a poor-quality image and a poor-quality scanned PDF.

#

# | Metric | Result |

# |---|---:|

# | Documents processed | 2/2 |

# | Document success rate | 100% |

# | Overall field exact-match accuracy | 81.25% |

# | Line-item exact-match rate | 100% |

# | Mean processing time | 9.67642 seconds/document |

#

# The degraded samples exposed extraction limitations:

# \- Subtotal exact-match accuracy: 50%.

# \- Currency exact-match accuracy: 0%.

# \- Other evaluated invoice fields: 100%.

#

# The system generated warnings for unsupported currency and missing subtotal values. These results demonstrate why manual review remains necessary for degraded documents.

#

# \### 3.3 Expected Invalid-Input Rejections

#

# | Input | Expected result | Actual result |

# |---|---|---|

# | Corrupted PDF | Reject | Rejected |

# | Corrupted JPG | Reject | Rejected |

# | Unsupported TXT | Reject | Rejected |

#

# Expected safe rejection rate: 3/3 (100%).

#

# These are expected invalid-input rejections, not failures to process supported valid documents.

#

# \## 4. Large PDF Text Extraction Benchmark

#

# A synthetic 1,000-page digital-text PDF was used to evaluate digital PDF text extraction.

#

# | Metric | Measured result |

# |---|---:|

# | Pages expected | 1,000 |

# | Pages extracted | 1,000 |

# | Generated PDF size | 591,549 bytes |

# | Extracted text | 283,891 characters |

# | Text extraction time | 0.292 seconds |

# | Throughput | 3,424.49 pages/second |

#

# This benchmark measures digital text extraction only. It does not measure scanned-page OCR, LLM extraction, database persistence, upload/API queue time or concurrent processing.

#

# \## 5. Automated Testing

#

# The backend automated test suite completed with:

#

# \- 91 tests passed.

# \- 1 warning.

#

# The warning was a Starlette/httpx test-client deprecation warning, not a test failure.

#

# The frontend production build also completed successfully during verification.

#

# \## 6. Additional Application Verification

#

# The following application workflows were manually verified:

#

# \- Multiple document uploads and batching.

# \- Document processing and dashboard status updates.

# \- Extracted document review and manual corrections.

# \- Processing history with before-and-after values.

# \- Keyword and semantic search workflows.

# \- Cross-document comparison with 53 completed documents.

# \- Mobile layout at a 390 x 844 viewport.

#

# These are functional checks, not additional labeled-dataset accuracy measurements.

#

# \## 7. Limitations

#

# The evaluation uses controlled synthetic data and relatively small sample sizes.

#

# The results do not establish:

# \- General accuracy on arbitrary real-world invoices.

# \- Accuracy across all supplier layouts or languages.

# \- Production OCR performance at scale.

# \- Performance under concurrent large uploads.

# \- End-to-end throughput for 1,000 scanned pages.

# \- Production availability or reliability guarantees.

#

# The degraded-document results demonstrate that extracted values can be incorrect or incomplete even when a document is processed successfully.

#

# \## 8. Conclusion

#

# The evaluation demonstrates successful operation across the tested synthetic document formats, invoice extraction, validation and expected invalid-input rejection scenarios.

#

# The results also identify areas requiring further improvement, particularly currency and subtotal extraction from degraded documents.

#

# The system should be treated as a document-review and data-extraction aid. Human verification remains necessary before financial data is used for high-impact decisions.

#

# \## 9. Reproducibility

#

# Relevant evaluation artifacts:

#

# \- `evaluation/ground\_truth.json`

# \- `evaluation/latest\_results.json`

# \- `evaluation/multiformat\_ground\_truth.json`

# \- `evaluation/multiformat\_results.json`

# \- `evaluation/benchmark\_1000\_pages.json`

#

# Evaluation scripts:

#

# \- `backend/scripts/evaluate.py`

# \- `backend/scripts/benchmark\_1000\_pages.py`

#

# Only synthetic or properly authorized data should be used in evaluation and demonstration.

#
