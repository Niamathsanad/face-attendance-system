# Project Proposal

## 1. Project title
AI-Based Face Recognition Attendance Management System with Real-Time Monitoring, Automated Reporting, and Attendance Analytics.

## 2. Abstract
Manual attendance is slow, error-prone and easy to falsify by proxy. This project builds a web-based attendance system that identifies
registered students or employees from a live webcam using a **pretrained** face-embedding model (InsightFace, CPU inference), records attendance in a
relational database with duplicate prevention enforced by the database itself, and gives administrators a dashboard with corrections and an audit trail,
analytics charts, and CSV/Excel reports. Unknown faces are never recorded. Because faces are biometric data, the design includes informed consent,
template-only storage (no photos), deletion on request, and a documented list of limitations (no liveness detection). The system is evaluated with a defined
test plan; no accuracy figures are claimed before that evaluation is carried out.

## 3. Introduction
Face recognition systems convert a face image into a numeric vector (embedding) and compare it with stored vectors. Modern pretrained networks make it feasible to build such a system on an ordinary laptop without training a model. The project integrates that AI component into a complete, secure, testable software system.

## 4. Background and motivation
Roll-call consumes lecture time; paper registers are hard to analyse; shared logins and proxy attendance undermine records. Contactless camera-based attendance can save time, but it raises privacy, fairness and security questions that a responsible university project should address explicitly.

## 5. Problem statement
How can attendance be recorded automatically and reliably from a webcam while (a) never crediting unknown people, (b) preventing duplicate records, (c) keeping accurate, auditable, correctable records, and (d) protecting biometric data?

## 6. Aim and objectives
**Aim:** deliver a working, secure face-recognition attendance system with analytics, suitable for a classroom demonstration.
Objectives: (1) select and justify a pretrained model that runs on CPU; (2) implement enrollment with image-quality validation; (3) implement real-time recognition with a configurable threshold; (4) implement sessions and attendance with database-level duplicate prevention; (5) build an admin dashboard, corrections with audit trail and reports; (6) implement authentication and web-security controls; (7) test automatically and evaluate recognition performance with a documented protocol; (8) document privacy measures and limitations.

## 7. Research questions
RQ1. How does the similarity threshold trade off false acceptance against false rejection on our own enrolled population?
RQ2. How do lighting, face angle and distance affect recognition?
RQ3. What end-to-end latency can be achieved on a CPU-only Windows laptop?
RQ4. Does requiring N consecutive matching frames reduce false attendance records, and at what delay cost?

## 8. Proposed methodology
Iterative development in 12 phases (see section 20). Pretrained model, no training. Evaluation: collect a held-out image set of enrolled and non-enrolled people (with consent), compute detection rate, FAR, FRR, precision, recall and latency at several thresholds, and repeat under controlled lighting/angle/distance conditions (section 18).

## 9. System architecture
See `system_architecture.md`: browser camera -> Flask routes -> services -> InsightFace model + SQLite. Pipeline: frame -> detection -> alignment -> embedding -> cosine similarity -> threshold/margin -> multi-frame confirmation -> attendance rules -> database insert -> dashboard.

## 10. AI model selection and justification
| Candidate | Notes |
|---|---|
| **InsightFace (ONNX) - chosen** | Actively maintained; detection + alignment + recognition in one API; ONNX Runtime runs on CPU; `buffalo_s` pack (~120 MB download) is small and fast, `buffalo_l` is larger and usually more accurate; embeddings are 512-D and L2-normalised so cosine similarity is a dot product |
| DeepFace (wrapper library) | Convenient, but pulls in large TensorFlow/Keras stacks, heavier installation on Windows |
| `face_recognition` (dlib) | Needs C++ build tools on Windows; older model |
| OpenCV YuNet + SFace | Lightweight alternative; kept as a future option |

Checked before selection: Python 3.12 compatibility (installs from pure-Python wheel `insightface 2.1` with pre-built Windows wheels for NumPy, OpenCV, ONNX Runtime, SciPy, scikit-image - no compiler required), CPU-only operation, pretrained model availability (downloaded automatically from the InsightFace model zoo on first run), and **licence**: the library is MIT, but the pretrained model packs are published for non-commercial research use - acceptable for coursework, must be re-checked for commercial use.
The default threshold (cosine 0.40) is only a starting value; it is configurable and must be tuned on the evaluation data.

## 11. Database design
Seven tables: administrators, students, face_embeddings, attendance_sessions, attendance_records, audit_logs, settings, with PK/FK/UNIQUE/CHECK constraints, indexes and cascade deletion. Details and ER diagram: `system_architecture.md`.

## 12. Functional requirements
FR1 admin login/logout; FR2 register person with consent; FR3 capture and validate face images; FR4 store embeddings; FR5 live detection/recognition with box, name, status; FR6 "Unknown Person" for no reliable match; FR7 multiple faces per frame; FR8 create/close sessions; FR9 automatic Present records without duplicates; FR10 search and filter records; FR11 correct records with reason and audit trail; FR12 attendance percentages; FR13 dashboard statistics and charts from live queries; FR14 day/week/month/person/group reports as CSV and Excel; FR15 delete biometric data / person; FR16 settings (threshold etc.).

## 13. Non-functional requirements
Security (hashing, CSRF, headers, access control); privacy (consent, minimisation, deletion); usability (responsive UI, clear errors); performance (interactive recognition on a CPU laptop; measured, not assumed); reliability (safe DB-error handling); maintainability (layered, modular, tested); portability (Windows 10/11, Python 3.12, no GPU); timezone correctness.

## 14. Hardware and software requirements
Hardware: Windows laptop, 4+ cores recommended, 8 GB RAM recommended (4 GB workable), integrated or USB webcam, ~1 GB free disk. No GPU.
Software: Python 3.12, VS Code, Git/GitHub, Chrome/Edge/Firefox; libraries in `requirements.txt` (Flask, NumPy, Pandas, OpenPyXL, OpenCV, ONNX Runtime, InsightFace); Bootstrap, Chart.js bundled locally. Internet only for installation and the first model download.

## 15. Project scope
In scope: single-site web application, one camera at a time in the browser (plus optional desktop window), SQLite, CPU inference, administrator users only.
Out of scope for this version: liveness detection, mobile apps, multi-camera/multi-site deployment, student self-service portal, LMS/ERP integration, database encryption.

## 16. Limitations
See `privacy_and_limitations.md` (no liveness, not proof of identity, lighting/pose/demographic effects, small-scale design).

## 17. Privacy and ethical considerations
Informed consent before enrollment; only templates stored; deletion/withdrawal supported; restricted access; alternative manual method; audit trail; transparency about limitations; recommended local data-protection approval for any use on real students; special care because biometric data is sensitive (e.g. treated as a special category of personal data under GDPR Art. 9; check your own jurisdiction/institution policy).

## 18. Testing and evaluation plan
**Automated software tests (implemented):** login, registration, duplicate IDs, enrollment, known/unknown recognition, duplicate-attendance prevention, sessions, date filters, calculations, reports, database failures, unauthorised access (`tests/`; see `testing_report.md`).
**Model evaluation (planned - to be run by the student with consenting volunteers):**
| Measure | Method |
|---|---|
| Detection rate | fraction of test images where exactly the expected face is detected |
| Precision / recall | on a held-out set of enrolled and non-enrolled people at the chosen threshold |
| FAR | non-enrolled (impostor) attempts wrongly accepted / total impostor attempts |
| FRR | enrolled attempts wrongly rejected / total genuine attempts |
| Threshold sweep | repeat at thresholds 0.25-0.60; plot FAR/FRR; choose operating point |
| Latency | time from frame received to decision, mean/95th percentile, on the target laptop |
| Attendance success rate | genuine attendances correctly recorded / attempts, in live trials |
| Lighting | bright, normal, dim, backlit |
| Angle / distance | 0, 15, 30, 45 degrees; 0.5, 1, 2, 3 m |
Use separate enrollment and test photos; report sample sizes and confidence; label any illustrative numbers as such. No results are invented in this document.

## 19. Expected outcomes
A working system meeting FR1-FR16, a test suite, a measured evaluation with an honest discussion of errors, and documentation (README, architecture, privacy, report, slides, viva material).

## 20. Project timeline (12 weeks, planning estimate)
| Weeks | Work |
|---|---|
| 1 | Idea, feasibility, literature, proposal |
| 2 | Architecture, database schema |
| 3 | Environment, database layer |
| 4 | Authentication, registration |
| 5 | Enrollment and recognition engine |
| 6 | Live recognition + attendance integration |
| 7-8 | Dashboard, records, corrections, reports |
| 9 | Security hardening, automated tests |
| 10 | Model evaluation data collection and analysis |
| 11 | Bug fixing, usability |
| 12 | Final report, slides, viva preparation |

## 21. Estimated development costs (planning estimate)
Software: all open-source/free (Python, Flask, InsightFace library, SQLite, Bootstrap, Chart.js, VS Code, Git/GitHub) = 0.
Hardware: existing laptop; an external USB webcam if needed (approx. USD 15-40, prices vary). Time: about 12 weeks of part-time student effort. For commercial use, model licensing would be an additional cost to investigate.

## 22. References (real, verifiable)
1. Deng, J., Guo, J., Xue, N., Zafeiriou, S. "ArcFace: Additive Angular Margin Loss for Deep Face Recognition." CVPR 2019. arXiv:1801.07698.
2. Guo, J., Deng, J., Lattas, A., Zafeiriou, S. "Sample and Computation Redistribution for Efficient Face Detection" (SCRFD). ICLR 2022. arXiv:2105.04714.
3. Deng, J., Guo, J., Ververas, E., Kotsia, I., Zafeiriou, S. "RetinaFace: Single-stage Dense Face Localisation in the Wild." CVPR 2020. arXiv:1905.00641.
4. Schroff, F., Kalenichenko, D., Philbin, J. "FaceNet: A Unified Embedding for Face Recognition and Clustering." CVPR 2015. arXiv:1503.03832.
5. Chen, S., Liu, Y., Gao, X., Han, Z. "MobileFaceNets: Efficient CNNs for Accurate Real-Time Face Verification on Mobile Devices." arXiv:1804.07573, 2018.
6. Huang, G. B., Ramesh, M., Berg, T., Learned-Miller, E. "Labeled Faces in the Wild: A Database for Studying Face Recognition in Unconstrained Environments." University of Massachusetts Amherst, Technical Report 07-49, 2007.
7. Grother, P., Ngan, M., Hanaoka, K. "Face Recognition Vendor Test (FRVT) Part 3: Demographic Effects." NISTIR 8280, National Institute of Standards and Technology, 2019.
8. ISO/IEC 30107-3: Biometric presentation attack detection - Part 3: Testing and reporting.
9. Regulation (EU) 2016/679 (GDPR), Article 9 - processing of special categories of personal data.
10. InsightFace project repository and model zoo documentation: https://github.com/deepinsight/insightface
11. ONNX Runtime documentation: https://onnxruntime.ai/docs/
12. OpenCV documentation: https://docs.opencv.org/
13. Flask documentation: https://flask.palletsprojects.com/
14. SQLite documentation (foreign keys, partial indexes): https://www.sqlite.org/docs.html
15. Chart.js documentation: https://www.chartjs.org/docs/
16. OWASP Cheat Sheet Series (Password Storage, CSRF Prevention): https://cheatsheetseries.owasp.org/
17. Python `zoneinfo` documentation: https://docs.python.org/3/library/zoneinfo.html

*Please open each reference yourself and confirm title, authors and year before submitting - this is good academic practice.*

## Feature status (planned vs completed)
| Feature | Status |
|---|---|
| FR1-FR16 | **Implemented and covered by automated tests** (browser camera behaviour could not be tested automatically here - test it on your laptop) |
| Real-model evaluation (FAR/FRR, lighting, angles) | **Planned - not yet performed** |
| Liveness detection, encryption at rest, HTTPS | **Planned / future work** |
