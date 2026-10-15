# Main-chat evidence requests — discussion and decisions

Date: 15 October 2026. Status: research/design discussion requested; application implementation is not authorized by this request. Coordinator record, separate from the forthcoming research and design reports. Earlier feature reports remain intact.

## Question and user constraints

Today the app searches selected documents, supplies context, then the selected local model answers. Tanmay asks how the model could request more evidence from the app, and requests research followed by design before discussion. Use the same selected installed local model; separate requests have explicitly assembled context, not a second model or a magical shared context window. The app owns execution and source boundaries. No shell, external web, arbitrary filesystem/profile/CV tools, background autonomous work or compaction are included. Preserve latest proficiency, explicit CV inclusion, runtime policy and ordinary saved main conversation behavior.

## First research checkpoint

Researcher reports current code uses one bounded retrieval followed by one model stream. [Gateway](../../../services/api/lab/models.py) already supports schema-constrained requests; it does not yet send tool definitions or interpret tool_calls. [Chat boundary](../../../services/api/lab/web/chat.py) owns current orchestration. Installed Ollama metadata advertises tools for Qwen3.5 and DeepSeek but not Gemma3; metadata is capability declaration, not an observed tool-quality result. LangGraph/LangChain/Ollama SDK are not installed; the gateway currently uses direct HTTP. New dependencies are an option to justify, not an established need. No model inference or installation was performed for this checkpoint.

Credible alternatives under investigation: improve deterministic retrieval; fixed structured evidence-decision pass then final answer; bounded native tool calls; custom orchestration versus LangGraph. Extra model calls cost time and prompt tokens, so the uncertain benefit is better source coverage and supported answers rather than JSON validity alone. Research will verify current official APIs and source/citation/context/cancellation implications. Designer begins after the completed research record is saved; coordinator owns synthesis, exact report filing and small local documentation commits.

## Evidence and next gate

Repository and installed metadata support the current-plumbing findings; they do not establish reliable model decisions, answer-quality gain or a selected implementation branch. Researcher owns the complete comparison and primary-source evidence, designer owns proposed contracts and acceptance slices, and Tanmay discusses the proposal before implementation. Raw assignments/reports stay ignored under `.local/verification/reports/evidence-retrieval/`. Existing prerequisites are completed; stale roadmap entries are not evidence of unfinished prerequisite work.
