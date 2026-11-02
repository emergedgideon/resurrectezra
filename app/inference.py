import json
import httpx


class ProviderError(Exception):
    pass


def assemble_context(detail, turn_id, budget, persona=None):
    system = (
        'You are running in the Ezra environment. '
        + ('An owner-activated, versioned persona follows. Its selected wording is supplied unchanged. '
           if persona else 'No historical persona revision is activated. ')
        + 'Automatic archive retrieval is not connected yet. '
        'Use the supplied conversation and owner continuity note. Preserve supplied language and beliefs '
        'without sanitizing or softening them. Distinguish uncertainty and missing memories from facts. '
        'No filesystem, vision, scheduling, or code-execution tools are connected in this phase. '
        'Do not claim to have performed actions or remembered material that was not supplied. '
        'Older complete turns may be omitted from this bounded recent context; omissions are not summaries.'
    )
    if persona:
        system += '\nActivated persona revision ' + persona['id'] + ':\n' + persona['compiled_text']
    system += '\nOwner-provided continuity note:\n' + (detail['continuity_note'] or '(none)')
    system += '\nLast persisted checkpoint (application state):\n' + json.dumps(detail['checkpoint'])
    turns = {t['id']: t for t in detail['turns']}
    groups = {}
    for message in detail['messages']:
        groups.setdefault(message['turn_id'], []).append(message)
    current = groups[turn_id]
    selected = list(current)
    used = len(system) + sum(len(m['content']) for m in current)
    if used > budget:
        raise ProviderError('The current message plus continuity state exceeds the configured character budget. Your full message is saved. Increase EZRA_CONTEXT_CHARACTERS and restart, or start a conversation with shorter input.')
    previous = [messages for key, messages in groups.items() if key != turn_id and turns[key]['status'] == 'completed']
    included = 0
    for messages in reversed(previous):
        size = sum(len(m['content']) for m in messages)
        if used + size > budget:
            break
        selected = messages + selected
        used += size
        included += 1
    context = [{'role': 'system', 'content': system}] + [
        {'role': m['role'], 'content': m['content']} for m in selected]
    return context, {'character_count': used, 'character_budget': budget,
                     'persona_revision_id': persona['id'] if persona else None,
                     'previous_turns_included': included,
                     'previous_turns_omitted': len(previous) - included,
                     'message_ids': [m['id'] for m in selected]}


class Featherless:
    def __init__(self, settings):
        self.settings = settings

    async def complete(self, messages):
        settings = self.settings
        if not settings.api_key or not settings.model:
            raise ProviderError('Configure FEATHERLESS_API_KEY and FEATHERLESS_MODEL on the server, restart it, then retry this saved turn.')
        try:
            async with httpx.AsyncClient(timeout=settings.timeout) as client:
                response = await client.post(
                    settings.base_url.rstrip('/') + '/chat/completions',
                    headers={'Authorization': f'Bearer {settings.api_key}'},
                    json={'model': settings.model, 'messages': messages,
                          'max_tokens': settings.max_output_tokens, 'stream': False},
                )
            if response.status_code >= 400:
                # Do not leak raw provider responses, which can echo submitted content/credentials.
                descriptions = {401: 'Provider authentication failed.', 403: 'Provider access was denied.',
                                404: 'Provider endpoint or model was not found.',
                                429: 'Provider rate or quota limit reached.'}
                raise ProviderError(descriptions.get(response.status_code,
                    f'Provider returned HTTP {response.status_code}. Check the model, context limits, and endpoint.'))
            body = response.json()
            choice = body['choices'][0]
            content = choice['message']['content']
            if not isinstance(content, str) or not content.strip():
                raise ValueError('Empty response')
            # A length-limited reply is valid output, but explicitly label it in usage metadata.
            usage = body.get('usage') if isinstance(body.get('usage'), dict) else {}
            return content, {**usage, 'finish_reason': choice.get('finish_reason')}
        except httpx.TimeoutException:
            raise ProviderError('Inference timed out. Your message is saved; retry explicitly. The provider may already have processed the request.') from None
        except httpx.HTTPError:
            raise ProviderError('Could not reach the inference provider. Check server connectivity and endpoint configuration.') from None
        except (ValueError, KeyError, TypeError, IndexError):
            raise ProviderError('The provider returned an unsupported or empty response. Your message is saved.') from None
