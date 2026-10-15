# Main-chat evidence requests — research

Date: 15 October 2026. Separate research-role findings, filed by the coordinator before design. Application baseline: `8f7e5a9`; subsequent coordinator commits contain discussion documentation only. This is investigation and a recommendation, not implementation approval or a measured quality result. The research agent read and acknowledged the complete development policy and research skill. No source/test/Git changes, installation, inference, model download, personal topic or CV access occurred.

Original role findings were returned in the `/root/researcher` final handoff in this conversation. Raw assignment and a local copy of this filed report live under ignored `.local/verification/reports/evidence-retrieval/`. The [coordinator discussion record](2026_10_15_evidence_retrieval_discussion.md) remains separate and preserves decisions/uncertainty for the walkthrough.

## Question and recommendation

How can the selected local model ask the application for more document evidence before answering? A request-bound module can do this without another chat model, hosted service, new conversation, Ollama SDK or LangGraph:

1. Capture the conversation and selected files, then run today's initial retrieval.
2. Ask the same selected model whether another lookup would help.
3. Validate and execute at most one registered lookup.
4. Assemble a bounded final prompt and answer with that same model.
5. Save one user turn and one final assistant answer with truthful evidence metadata.

Recommend designing this bounded experiment, comparing a short JSON-schema decision against one-round native tool calling and a deterministic retrieval improvement. The existing schema gateway makes JSON the smallest first experiment, not automatically the best production protocol. No open-ended loop or framework is justified before measuring usefulness and cost.

## Verified repository behavior

| Finding | Repository evidence and consequence |
| --- | --- |
| Default/named chats share orchestration | [web/chat.py](../../../services/api/lab/web/chat.py), lines63–69: one implementation can cover both without a side chat. |
| Policy is freshly loaded before retrieval/generation | web/chat.py:165; [runtime_policy.py](../../../services/api/lab/runtime_policy.py):8–18. Keep the complete turn policy snapshot in every subrequest; invalid policy must block visibly. |
| Topic and selected files are bound at request boundary | web/chat.py:175–209. Ready indexed files are searched; unindexed parser output is supplied as attachment Markdown. |
| One current search uses the user's message | [retrieval.py](../../../services/api/lab/retrieval.py):62–132; web/chat.py:193–201. Hybrid keyword/embedding search visibly degrades to keywords on embedding failure. |
| No-match fallback can return opening passages | retrieval.py:108–123. Receiving passages does not establish a meaningful match; a new tool must expose this distinction. |
| Evidence receives prompt/source metadata | retrieval.py:160–204. Saved citations must identify evidence actually retained for final inference. |
| Context allocation can discard whole retrieved passages | [chat_prompt.py](../../../services/api/lab/chat_prompt.py):37–39,88–112; [context.py](../../../services/api/lab/context.py):113–135. More retrieval is not necessarily more retained evidence. |
| Policy, learner context and opted-in whole CV are protected | chat_prompt.py:40–104; [learner_context.py](../../../services/api/lab/learner_context.py):123–144. CV context must remain outside the search corpus. |
| Explicit whole-question protection is conditional | chat_prompt.py:84–86; context.py:124–126. The new planner/final contracts must explicitly retain the complete question regardless of profile/CV presence. This inspection is not a reproduced current-data-loss claim. |
| User save/cancellation already have lifecycle ownership | web/chat.py:254–257,310–371. User message is saved after initial preflight; answer cleanup preserves incomplete output and releases topic lease. Define new persistence boundaries explicitly. |
| Gateway and embeddings share a generation lock | [web/deps.py](../../../services/api/lab/web/deps.py):39–60; [models.py](../../../services/api/lab/models.py):106,159. Fully consume/close the decision stream before retrieval embedding; no outer copy of this lock around the loop. |
| Schema output exists; native tool interface does not | [contracts.py](../../../services/api/lab/contracts.py):154–164; models.py:184–222. Existing gateway sends format/temperature0 but neither tools nor parses tool_calls. |
| Generation and embedding request keep_alive0 | models.py:121,188. Extra requests may incur unloading/loading costs, requiring actual timing. |
| History belongs to the app | [chat_session.py](../../../services/api/lab/chat_session.py):8–30; web/chat.py:241–255,380–387. Every model call receives an explicit message list. |
| Traces and browser events currently assume today's stages | [query_traces.py](../../../services/api/lab/query_traces.py):19–108; [trace contract](../../query_traces.md); [web types](../../../apps/web/src/api/types.ts):272–282. Stage diagnostics and status events need explicit compatibility decisions. |

The [existing retrieval evaluation](../retrieval-evaluation/retrieval_eval_validation.md) documents both missed evidence and retrieved evidence lost during prompt retention. Its generation is simulated. Source-anchor metrics alone do not prove answer support, semantic correctness or abstention.

## Observed installed capabilities

Read-only metadata showed httpx0.28.1, FastAPI0.141.1, Docling2.127.0 and Ollama0.40.4. LangGraph, LangChain and Ollama Python SDK were absent.

| Installed model | Server-reported capabilities |
| --- | --- |
| qwen3.5:9b-q4_K_M | completion, vision, tools, thinking |
| qwen3.5:4b-q8_0 | completion, vision, tools, thinking |
| gemma3:12b | completion, vision |
| deepseek-r1:14b | tools, thinking, completion |
| nomic-embed-text:latest | embedding |

Capability labels do not establish useful tool choice, valid arguments, good stopping behavior or comparable quantization performance. Current model listing exposes vision/thinking but not tool capability (models.py:60–91). The same selected chat model can make the decision and final answer. Existing hybrid retrieval may still use its already installed embedding model; this does not introduce another routing/chat model.

## Concrete exchange and request context

Proposed illustrative schema output, not an existing API:

```json
{"action":"search","query":"Appendix B comparison motivating the selected method","file_ids":["selected-paper-id"]}
```

An alternative decision could be `{"action":"answer","query":"","file_ids":[]}`. Designer must define strict variants and limits. App code captures topic/conversation, checks any requested file IDs against the selection, executes only registered operations, deduplicates evidence, enforces budget and builds source metadata. A filename or tool-name string grants no authority.

The final call explicitly supplies policy, question/conversation context, retained evidence and new results. It is not an empty-context call expected to remember the previous request. Keeping model weights resident also does not create durable conversation memory.

Native Ollama calls use tools definitions and structured message.tool_calls. The app supplies the assistant request and its own role:tool result on continuation. A streamed response may combine text, thinking and tool-call data; planning output must not accidentally become a completed answer. See [official tool-calling protocol](https://docs.ollama.com/capabilities/tool-calling).

Schema decisions instead use the format JSON-schema option already integrated here, followed by app validation. Temperature0 improves repeatability without proving useful decisions. See [official structured-output documentation](https://docs.ollama.com/capabilities/structured-outputs). The chat API receives an explicit messages array and returns timing/token counters; keep_alive0 requests immediate unloading. See [official chat API](https://docs.ollama.com/api/chat).

## Alternatives actually considered

| Approach | Benefit | Cost or uncertainty |
| --- | --- | --- |
| Deterministic neighbour expansion, file coverage or evidence prioritization | No additional chat-model decision; preserves current one-generation path; addresses measured misses/retention | Cannot reliably formulate a new query from unfamiliar cross-references |
| Fixed schema decision, one lookup, normal final answer | Existing gateway; finite stages; no native-tools capability dependency | Extra call even with no useful lookup; repeated prompt; JSON validity is not good judgment |
| One-round native tools | Provider-native action representation; may answer in one call if no tool needed | Gateway/events/capability changes; mixed text/action output requires buffering or staged UI |
| Several native rounds | Can pursue multiple dependencies | Added latency, repeated context, duplicate requests, stop/overflow complexity; unproven need |
| Custom finite orchestrator | Inspectable module around existing locks/policy/storage; no install | Project owns transitions and diagnostics |
| LangGraph | Explicit orchestration and later checkpoint/resume/interrupt facilities | Does not solve model quality, authorization, source identity or budgets; additional state ownership |

Buffering a native first response until its terminal event avoids presenting provisional text as final, but delays visible answer text. A distinct schema decision stage makes this explicit at the cost of another call. This is a product/protocol tradeoff to settle consciously.

[LangGraph's official overview](https://docs.langchain.com/oss/python/langgraph/overview) describes an orchestration runtime usable without LangChain. It is not necessary for a bounded exchange. Its [persistence facilities](https://docs.langchain.com/oss/python/langgraph/persistence) become more relevant with durable intermediate resume; adopting them alongside app-owned conversation/profile storage requires a separate compatibility decision.

## Possible document operations

**Search selected indexed documents** is the smallest first operation. Reuse retrieval.search with server-bound topic and selected indexed IDs. Never translate empty scope to None: the lower index interface treats None as unfiltered topic scope ([index.py](../../../services/api/lab/index.py):397–455).

**Read neighbours** is feasible using stable chunk_index/exact chunk records. There is no purpose-built bounded neighbour operation; add a scoped query if chosen instead of loading a whole large file. Anchors must resolve within allowed files; invented IDs fail validation.

**Read map section** can reuse get_document_map, get_document_map_section and section_sources. However, model-visible section IDs need discovery; only already-built current maps fit read-only behavior; native map units differ from retrieval chunks and need honest citation representation; complete section must fit whole or refuse; not every parser has a map. Do not secretly build/repair maps, summarize sections or generate prerequisites as source tools.

Recommend search-only first to separate these questions. Follow with neighbours/sections only if the experiment demonstrates a need. Current built-in prompt says no file/shell/web/device tools; a future prompt must describe precise document operations while preserving the configured runtime policy and other restrictions. Development authorization does not grant general tools to the learning model.

## Proposed experiment and acceptance

No inference experiment was run. After approval, an implementation agent owns an isolated harness; research/review verifies comparison and usage verifies product outcomes. Compare current baseline, one deterministic expansion/prioritization variant, one schema follow-up decision and optionally one native round under the same selected model, fixtures, policy and context budget.

Cases: directly answerable passage; missing cross-reference/multi-section comparison; neighbouring definition; unsupported question; history-dependent follow-up; selected-file trap; malicious document instruction; malformed/unknown/repeated/oversized/multiple actions; cancellation in every stage; protected CV/new-evidence overflow; stale map only if section tools are included.

Measure retrieved and retained support separately; manually inspect actual answers/abstention. Record action validity, unnecessary lookups, total generation calls, available prompt/output counters, time to first final text and total latency. Existing simulated-generation scores are not a substitute.

Hard gates: no scope escape; finite calls/lookups/no hidden retry; provider closure and lock release; no planning JSON completed as answer; final citations match final supplied evidence; protected inputs never silently shortened; visible degradation/unavailability/fit failures; old histories remain readable.

Agree quality/cost gates before the experiment. Useful support on difficult cases must justify observed latency without systematically unnecessary lookup or more confident unsupported answers. Current evidence supports no numerical improvement/speed threshold.

Trace additions should record stage counts/times, operation kind, validated source IDs, outcomes and retained IDs; do not duplicate prompts, passages, CV text, raw thinking or free-form queries in compact diagnostics.

## Conditions that would change the recommendation

Prefer deterministic improvements if they achieve comparable support more cheaply. Prefer native actions if reliability and streaming UX are demonstrated; otherwise make capability limits/fallback explicit without switching models. Consider another bounded round only after one lookup is insufficient in measured cases. Consider LangGraph when durable workflow resume/approval is required. Repair retention allocation before increasing search volume if retrieved evidence is being discarded.

Verified: code tracing, installed metadata and current primary documentation. Not run: application tests/build, parser/inference/browser experiments, latency, answer-quality or new-protocol compatibility checks. These remain validation gates rather than claimed results.
