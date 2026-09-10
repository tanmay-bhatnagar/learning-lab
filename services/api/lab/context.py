"""Ephemeral prompt budgeting; never modifies the caller's durable history."""
from copy import deepcopy
import json

DEFAULT_CONTEXT_LIMIT = 8192
MAX_CONTEXT_LIMIT = 32768


def estimate_tokens(text: str) -> int:
    """One estimated token per UTF-8 byte: deliberately very conservative.

    This can substantially overestimate ordinary text and trim earlier than a
    real tokenizer would. Metadata remains estimated until Ollama returns both
    prompt_eval_count and eval_count; those actual counts replace this estimate.
    """
    return len(text.encode('utf-8'))


def estimate_messages(messages: list[dict]) -> int:
    # Template framing is model-specific; allow overhead per message and reply.
    return 32 + sum(16 + estimate_tokens(json.dumps(m, ensure_ascii=False)) for m in messages)


def prepare_context(messages: list[dict], context_limit: int = DEFAULT_CONTEXT_LIMIT):
    """Return (copied prompt, context metadata, bounded generation budget).

    User turns are atomic, including assistant tool calls and tool replies.
    Consecutive user-context/attachment messages form independently removable
    groups. After older turns go, the newest standalone user context immediately
    preceding the latest user retains the largest suffix that fits alongside the
    full question. Only then may the question itself be shortened from the front.
    System messages are retained in their original positions and never shortened.
    truncated_messages counts each removed or shortened message once.
    """
    if type(context_limit) is not int or not 256 <= context_limit <= MAX_CONTEXT_LIMIT:
        raise ValueError('context_limit must be an integer between 256 and 32768')
    reserve = min(2048, max(64, context_limit // 4))
    budget = context_limit - reserve
    copied = deepcopy(messages)
    for message in copied:
        if message.get('role') not in {'system', 'user', 'assistant', 'tool'}:
            raise ValueError('Unsupported message role')
        if not isinstance(message.get('content', ''), str):
            raise ValueError('Message content must be text')
    groups = []
    for index, message in enumerate(copied):
        if message['role'] == 'system':
            continue
        if message['role'] == 'user' or not groups:
            groups.append([])
        groups[-1].append(index)
    latest_user = next((i for i in range(len(copied) - 1, -1, -1)
                        if copied[i]['role'] == 'user'), None)
    latest_group = next((i for i, group in enumerate(groups) if latest_user in group), None)
    attachment = None
    if latest_group is not None and latest_group > 0:
        previous = groups[latest_group - 1]
        if len(previous) == 1 and copied[previous[0]]['role'] == 'user':
            attachment = previous[0]
    keep = set(range(len(copied)))
    affected = set()

    def selected():
        return [m for i, m in enumerate(copied) if i in keep]

    def shorten(index):
        """Keep the longest suffix fitting the current selection, if possible."""
        original = copied[index].get('content', '')
        copied[index]['content'] = ''
        if estimate_messages(selected()) > budget:
            copied[index]['content'] = original
            return False
        low, high = 0, len(original)
        while low < high:
            middle = (low + high + 1) // 2
            copied[index]['content'] = original[-middle:]
            if estimate_messages(selected()) <= budget:
                low = middle
            else:
                high = middle - 1
        copied[index]['content'] = original[-low:] if low else ''
        if low != len(original):
            affected.add(index)
        return True

    for group in groups:
        if estimate_messages(selected()) <= budget:
            break
        if latest_user in group:
            break
        if attachment in group and shorten(attachment):
            break
        keep.difference_update(group)
        affected.update(group)
    if estimate_messages(selected()) > budget and latest_user is not None:
        if not shorten(latest_user):
            raise ValueError('System messages or protected tool group exceed prompt budget')
    prompt = selected()
    used = estimate_messages(prompt)
    if used > budget:
        raise ValueError('System messages exceed prompt budget')
    return prompt, {'used': used, 'limit': context_limit, 'estimated': True,
                    'truncated_messages': len(affected)}, reserve
