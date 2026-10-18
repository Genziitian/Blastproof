# Blast Radius — rules and submission audit

Checked 18 October 2026 against the [official rules](https://www.wemakedevs.org/hackathons/falkordb/rules), [track brief](https://www.wemakedevs.org/hackathons/falkordb) and [Code of Conduct](https://www.wemakedevs.org/coc), plus source, saved verification artifacts, anonymous GitHub API responses and the deployed public API.

**Verdict:** The implementation supports Track 02 and the central FalkorDB requirements. The demo video has been supplied at [https://youtu.be/ubFTOB0ZIh0](https://youtu.be/ubFTOB0ZIh0) and is linked throughout the project. The latest intended source changes are included in this publication. Final form submission has not been verified; anonymous video playback still needs a team check because YouTube access was blocked in the verification environment. Technical checks cannot certify participant understanding, originality or conduct; those remain participant responsibilities and organiser judgments.

The user confirmed on this chat that Sri Ram and Aditi Akansha each belong only to this team, and that main coding/design work began after October 15, 12:01 AM IST. The user subsequently supplied the uploaded demo video: https://youtu.be/ubFTOB0ZIh0.

## Every rule

| Rule | Status | Evidence or remaining action |
|---|---|---|
| 1. Solo/team ≤4; one team per participant | Confirmed by user | Two listed members: Sri Ram and Aditi Akansha; user confirmed exclusive team membership. Registration roster itself was not inspected. |
| 2. FalkorDB is primary and central | Verified | Persistent playbooks, facts, incidents, conversations, decisions and coordination state are in company graphs. `common/db.py`, `memory/queries`, `coord/queries`, `chat/queries`. |
| 3. Graph does real work | Verified | Dependency/same-kind retrieval selects what to check; graph leases/checkpoints drive takeover. Removing FalkorDB blocks these workflows. Static blog and saved benchmark artifacts can still render; those are not the agent product. |
| 4. Accepted hosting/platform | Verified | FalkorDB Docker instance, Python app and isolated VPS deployment; these are permitted hosting choices. |
| 5. Name entered tracks | Draft ready; form not verified | README and submission draft name **Agent Memory and Coordination** (primary) and **Agents That Act on Connected Data**. Copy both into the form if entering both. The video focuses Track 02. Company Brain is not claimed. |
| 6. Allowed data only | Supported for reviewed demo | `sim/world.py`, simulator evidence and seeded engineer personas are synthetic. No production telemetry or private company dataset is required for the demonstrated path. This is not a forensic audit of every possible user-entered record. Synthetic data is expressly allowed; real execution is still required. |
| 7. Submit within event window | Pending final submission | Official deadline: **18 October 2026, 11:59 PM IST**. No completed submission receipt was inspected. |
| 8. Main work begins after start | Confirmed by user; history consistent | User confirmed. Earliest local commit is 15 October 2026, 15:57:52 UTC = 21:27:52 IST, after the 00:01 IST start. Commit timestamps alone do not prove when coding actually began. |
| 9. Permitted dependencies/assets; original event work judged | Supported; attribution retained | Dependency versions are recorded; Inter and JetBrains Mono license files are included. Using frameworks and assistants is allowed. No exhaustive third-party provenance review was performed. |
| 10. Required submission artifacts | Present; final link checks remain | Public repo, README/model, Cypher, deployment and supplied video URL are present. Current source changes are included in this publication. Team must verify anonymous playback and final form links. |
| 11. Disclose AI assistance | Present; local disclosure expanded | README already disclosed Claude, ChatGPT, Gemini and Claude Code. Local update adds the later ChatGPT/Codex portal verification, results fixes, deployment, blog and demo-script work. Publish this update too. |
| 12. Participants can explain implementation | Team demonstration required | `docs/TEAM-BRIEFING.md` and the new bilingual script explain graph model, Cypher, architecture and trade-offs. A document or a passed test cannot prove participant understanding. Rehearse explanations in your own words. |
| 13. Meaningful participant contribution/verification | Team evidence required | Design decisions and verification evidence exist; AI involvement is disclosed. Team must accurately explain its own contribution and decisions. Eligibility on this point cannot be guaranteed by a source-code audit. |
| 14. Prize allocation | Informational | No implementation change is required. Awards remain the organisers' decision. |
| 15. Participant/team IP | Team responsibility | Decide ownership internally. The public GitHub API reports no repository license; these hackathon rules do not explicitly require choosing one. No ownership agreement was inspected or created. |
| 16. Respectful behaviour | Ongoing participant responsibility | Conduct across chats/events is outside a code audit. No violation established by this review. |
| 17. No harassment, discrimination, plagiarism or manipulation | Ongoing participant responsibility | No violation established; the audit cannot certify all conduct or exhaustive originality. Present measured results with their dates, scope and limitations. |
| 18. Follow rules and Code of Conduct | Ongoing; submission gaps remain | Read and follow the official Code of Conduct. Close the video, repository-publication and final-submission items; this report is not an organiser approval. |

## Rule 10, item by item

| Required item | What was verified | State |
|---|---|---|
| Public source-code repo | Anonymous GitHub API: `private=false`, default branch main, initially checked public commit `ecaa0c4ed1cc21bffdb47e488d277151646848d8` | Public; latest updates included in this publication |
| README with setup and graph model | `README.md`: Run it, Graph data model, Track 02 mapping and limitations | Present |
| Cypher queries or graph algorithms | 76 query files indexed in `docs/QUERIES.md`; `algo.pageRank` and `algo.SPpaths` tools | Present |
| Video showing working project | User supplied https://youtu.be/ubFTOB0ZIh0; linked in README, landing, blog and submission draft | URL present; team playback check remains |
| Live deployment or complete local setup | https://blast.genziitian.in/mission-control and README local setup | Present |
| Entered track(s) | Track 02 primary; Track 01 additionally named in draft | Draft ready; form must match |

## Track 02 coverage

| Focus | Actual implementation and evidence |
|---|---|
| Episodic memory | Stored incidents, immutable decisions and checkpoints. |
| Semantic memory | Engineer-approved, sourced, time-valid preferences; old versions retained through supersession. |
| Procedural memory | Playbooks with executable preconditions, expected evidence and conclusion; trust/retirement updates. |
| Persistent conversation | War-room messages and sessions; s01 preference cited in s04 after the independent persistence test. |
| Shared state and handoffs | Graph tasks: investigator → responder → learner; checkpoint 3 → real SIGKILL → checkpoint 4 under epoch 2. |
| Concurrent reads/writes | Recorded two-company load configurations with 1/2/4 worker pairs and forced lease expiry; 20/20 completion and zero duplicates in each selected configuration. This is a bounded workload, not unlimited-concurrency certification. |
| Separate user/tenant memory | One graph per company, server-chosen graph routing; engineer-scoped preferences; marker checks find zero cross-tenant leaks. This is demo isolation, not production login/RBAC. |

## Claims to use accurately in the video

- Current public API selects `2026-10-18T15-42-49Z-rule-based`, max_steps 12, `hash-256` text embeddings. All A/B/C arms have 30/30 diagnoses correct. Mean tool calls: A 5.967, B 7.633, C 5.067.
- Graph recall@5 is 21/21; text recall@5 is 10/21 (about 48%). The pool is small (at most three active playbooks). Do not call it universal retrieval superiority.
- Selected load configurations each complete 20/20 with zero duplicate logical notification records. Isolation: zero other-tenant markers. Fencing: 5/5 stale writes rejected.
- The 71% model-request saving is from the separate, recorded **Oct 16** model run: A 192, C 55, both 30/30 accuracy; recall@5 graph 20/20, text 11/20. Do not put these figures over the latest deterministic Results tab.
- A real worker SIGKILL and a graceful database restart have been independently verified in the earlier session. RDB snapshots still have a documented potential loss window on a hard database crash; avoid “nothing can ever be lost”.
- Notifications are logical Action records. Do not claim actual Slack/ticket-provider delivery or a production paging integration.
- The public app executes real workers with a scripted engineer and resets/reseeds between rounds and on app startup. Public restart/reset is not a no-reseed persistence demonstration. Use a genuine local persistence recording.

## Remaining actions in priority order

1. Check anonymous playback of https://youtu.be/ubFTOB0ZIh0, then use that exact URL in the final submission form. The repository and public pages already link the supplied video.
2. Confirm public main contains this publication, including result-reader/benchmark files, dated artifacts, tests, blog and disclosure. Unrelated untracked patent-research notes are excluded.
3. Confirm the form names the same team and tracks as the README. Use https://blast.genziitian.in/mission-control for the live demo and https://blast.genziitian.in/blog/ for the write-up.
4. Submit before **11:59 PM IST, 18 October**, then verify the receipt/status and links. Form submission was not performed as part of this audit.
5. Rehearse the five technical explanations in the bilingual script. Disclose actual assistant work and describe your own decisions truthfully.

## Verification scope

This turn checked the official published rules/track/Code of Conduct, local source and history, the public repo metadata/commit, and current live settings/results. The initial audit did not reset the portal, restart the VPS, run a paid model evaluation, submit a form, push code or contact anyone. A subsequent user-authorized publication adds the video link, deploys the static-page updates and pushes the intended project changes; unrelated research notes are excluded.

Earlier saved evidence: full post-fix suite 202 tests, 201 passed / 1 intentional skip (`portal-fix-evidence/tests.log` in the shared workspace); independent no-reseed restart and acceptance 7/7 (`verification-2026-10-18/VERIFICATION.md`); current live-result snapshot saved alongside this report. Those tests were not rerun during this documentation-only change.
