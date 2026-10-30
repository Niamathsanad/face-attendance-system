# Presentation Outline (about 15 minutes) and Viva Questions

## Slide outline
1. Title, name, supervisor
2. Problem: manual attendance (time, proxy, records)
3. Objectives and scope
4. How face recognition works: detect -> align -> embed -> compare (pretrained, no training)
5. System architecture diagram (`system_architecture.md`)
6. Database ER diagram + the UNIQUE constraint
7. AI pipeline vs ordinary application logic
8. Demo 1: register + enroll (show consent, quality checks, "photos not stored")
9. Demo 2: session -> live recognition -> marked; show Unknown Person; show duplicate blocked
10. Demo 3: correction + audit log; dashboard; Excel report
11. Security: hashing, CSRF, lock-out, headers, access control
12. Privacy and ethics: consent, deletion, alternative method
13. Testing: 110 automated tests; real-model observations (small sample, honestly labelled)
14. Evaluation plan and results (FAR/FRR/latency - only YOUR measured numbers)
15. Limitations (no liveness, lighting, demographics, scale) and future work
16. Conclusion and questions

Demo tips: run `python seed_demo.py --history` beforehand; have a spare session ready; keep good front lighting; if the camera fails, demo recognition with `Upload photos` enrollment and the desktop script; mention the manual correction fallback.

## Viva questions and answers
1. **What is the difference between face detection and recognition?** Detection locates faces in an image; recognition decides whose face it is by comparing embeddings with enrolled people.
2. **What is an embedding?** A vector of 512 numbers produced by a neural network; faces of the same person produce vectors that are close together.
3. **Why cosine similarity?** Embeddings are L2-normalised, so the dot product equals the cosine of the angle between them: 1 = identical direction, about 0 = unrelated. It is fast and scale-independent.
4. **What does the threshold do?** It is the minimum similarity to accept a match. Raising it lowers false accepts but raises false rejects. It must be tuned on real data; ours (0.40) is only a starting value.
5. **Did you train a model?** No. A pretrained InsightFace model is used; training from scratch needs huge datasets and GPUs. Our contribution is the integration, rules, security and evaluation.
6. **Which parts are AI and which are normal code?** Detection and embedding extraction are pretrained AI; similarity, thresholds, confirmation, attendance rules, database, security and reports are ordinary application logic.
7. **How do you prevent duplicate attendance?** `UNIQUE(session_id, student_id)` in the database. Even simultaneous requests cannot insert twice; the second insert fails and we report "already recorded".
8. **How do you stop unknown people being marked?** Attendance is only inserted for a matched registered identity above threshold and margin, confirmed over several frames. Otherwise the label is "Unknown Person" and no row is written (tested).
9. **Why require several consecutive frames?** A single frame can be a lucky false match; N consecutive matches greatly reduce one-off errors, at a small delay.
10. **What is the margin check?** The best person must beat the second-best person by a margin; otherwise the match is ambiguous and treated as unknown.
11. **How are embeddings stored?** As float32 bytes in a BLOB (2048 bytes) with dimension and model name. Photos are not stored.
12. **What if the model is changed?** Embeddings are model-specific; templates record `model_name` and only matching ones are loaded, so people must be re-enrolled.
13. **How is a person's biometric data deleted?** *Delete face data* removes templates and marks consent withdrawn; *Delete person* cascades through foreign keys. `secure_delete` overwrites freed pages. Both are audit-logged.
14. **How are passwords protected?** Salted PBKDF2-SHA256 (600 000 iterations) hashes; the default admin must change the password at first login.
15. **What is CSRF and how do you prevent it?** A malicious site making the logged-in admin's browser send requests. Every POST needs a secret per-session token; cookies are SameSite=Lax.
16. **How do you prevent SQL injection and XSS?** Parameterised queries; Jinja escaping; no inline scripts; CSP.
17. **How is "absent" determined?** A person expected in a session (registered by then, inside the session scope) with no Present record. It is derived by one SQL query, so all screens and reports agree.
18. **How do you distinguish corrections from real recordings?** Records carry `source` and `is_corrected`; the UI labels "Recorded by camera" vs "Manual correction", original status and reason are kept, and every correction is in the audit log.
19. **Which timezone is used?** Stored in UTC; displayed and exported in the configured zone (default Asia/Karachi); documented in exports.
20. **What are the system's weaknesses?** No liveness detection (photo/video spoofing), sensitive to lighting/pose/occlusion, possible demographic performance differences, SQLite/single-server scale, no encryption at rest.
21. **How would you add liveness detection?** Use a dedicated anti-spoofing model or challenge-response (blink/turn), and evaluate it separately with presentation-attack tests (ISO/IEC 30107-3 methodology).
22. **How do you measure accuracy?** Held-out test images; FAR, FRR, precision, recall at several thresholds; per-condition tests; latency. We did not claim figures we have not measured.
23. **What is FAR vs FRR?** FAR = impostors wrongly accepted / impostor attempts; FRR = genuine users wrongly rejected / genuine attempts.
24. **Why Flask and SQLite?** Simple, lightweight, easy to demo on a laptop; SQLite is serverless. For many users use PostgreSQL and a production server.
25. **Is face recognition legal/ethical to use for attendance?** It needs informed consent, a lawful basis, minimisation, security, an alternative method and institutional approval; rules vary by country - check local law and policy.
26. **Why does the camera run in the browser?** Works on any laptop, user grants permission explicitly, integrates with the dashboard; frames go only to the local server and are discarded.
27. **What would you improve first?** Run the full evaluation with volunteers, then add liveness detection and encryption at rest.
