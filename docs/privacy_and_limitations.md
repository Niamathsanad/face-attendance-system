# Privacy, Ethics and Limitations

## Biometric data protection (as implemented)
| Principle | Implementation |
|---|---|
| Informed consent | Registration cannot be saved without the consent tick; consent status and date are stored; enrollment is refused when consent is `withdrawn` |
| Data minimisation | Only a 512-number template is stored. Captured photos exist in browser/server memory during the request only. No video is recorded. |
| Access control | All pages and APIs need an administrator session; templates are never sent to the browser or placed in public folders |
| Deletion / withdrawal | *Delete face data* (withdraws consent) and *Delete person* (cascade) in the Registered-people page, both audit-logged |
| Retention recommendation | Delete templates when a person leaves the course/organisation, or at the end of the academic term; document this in your institution's policy |
| Alternative method | Administrators can mark attendance manually (*Correct*), so nobody is forced to use face recognition |
| Transparency | The live page states that frames are not stored; the audit log lists every enrollment, deletion, correction and export |

## Known limitations (state these honestly in your presentation)
1. **No liveness detection / presentation-attack protection.** A printed photo or a phone video may be accepted. Do not use this version where fraud matters. If liveness is added later it must be evaluated separately (see ISO/IEC 30107-3 for PAD testing methodology).
2. **Not proof of identity.** A similarity score is a statistical estimate; errors in both directions will happen. Use corrections and human review.
3. **Lighting, pose, distance, occlusion** (masks, glasses, hats, strong backlight, faces under about 80 px) reduce accuracy.
4. **Demographic differences.** Published evaluations of face-recognition algorithms (e.g. NIST FRVT Part 3) found that error rates can differ between demographic groups. The accuracy of this system for your population is unknown until you measure it.
5. **Small enrollment sets** (1-3 photos) give weaker templates than 5+ varied photos.
6. **Threshold dependence.** 0.40 is a starting value based on a handful of sample photos, not a validated operating point.
7. **Single-machine design.** SQLite, in-process caches and a development server suit a demo or one classroom, not a campus deployment.
8. **No encryption at rest, no HTTPS by default.**
9. **Model licence.** The pretrained model packs are for non-commercial research use according to the InsightFace project; verify before commercial use.

## Future improvements
Liveness / anti-spoofing (evaluated separately), encrypted database, HTTPS reverse proxy, role-based access (teacher vs admin),
automatic session scheduling, email notifications, PostgreSQL, GPU inference, per-site threshold calibration, retention-period automation.
