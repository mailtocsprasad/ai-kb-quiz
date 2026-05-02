# Prompt Caching (Anthropic API)

Prompt caching optimizes API usage by allowing you to resume from specific prefixes in your prompts, significantly reducing processing time and costs for repetitive tasks or prompts with consistent elements.

## How Prompt Caching Works

When you send a request with prompt caching enabled:

1. The system checks if a prompt prefix, up to a specified cache breakpoint, is already cached from a recent query.
2. If found, it uses the cached version, reducing processing time and costs.
3. Otherwise, it processes the full prompt and caches the prefix once the response begins.

By default, the cache has a **5-minute lifetime**. The cache is refreshed at no additional cost each time the cached content is used. A **1-hour cache duration** is also available at additional cost.

Prompt caching caches the full prefix: `tools`, `system`, and `messages` (in that order) up to and including the block designated with `cache_control`.

This is especially useful for:
- Prompts with many examples
- Large amounts of context or background information
- Repetitive tasks with consistent instructions
- Long multi-turn conversations

## Two Ways to Enable Prompt Caching

### Automatic Caching

Add a single `cache_control` field at the top level of your request. The system automatically applies the cache breakpoint to the last cacheable block and moves it forward as conversations grow. Best for multi-turn conversations.

```python
response = client.messages.create(
    model="claude-opus-4-7",
    max_tokens=1024,
    cache_control={"type": "ephemeral"},
    system="You are a helpful assistant that remembers our conversation.",
    messages=[
        {"role": "user", "content": "My name is Alex. I work on machine learning."},
        {"role": "assistant", "content": "Nice to meet you, Alex!"},
        {"role": "user", "content": "What did I say I work on?"},
    ],
)
```

### Explicit Cache Breakpoints

Place `cache_control` directly on individual content blocks for fine-grained control over exactly what gets cached.

```json
{
  "model": "claude-opus-4-7",
  "max_tokens": 1024,
  "system": [
    {
      "type": "text",
      "text": "You are an expert assistant with access to a large knowledge base...",
      "cache_control": {"type": "ephemeral"}
    }
  ],
  "messages": [{"role": "user", "content": "Summarize the key points."}]
}
```

## How Automatic Caching Works in Multi-Turn Conversations

The cache point moves forward automatically as conversations grow:

| Request | Cache behavior |
|---------|----------------|
| Request 1: System + User(1) + Asst(1) + **User(2)** | Everything written to cache |
| Request 2: ... + User(2) + Asst(2) + **User(3)** | System through User(2) read from cache; Asst(2)+User(3) written |
| Request 3: ... + User(3) + Asst(3) + **User(4)** | System through User(3) read from cache; Asst(3)+User(4) written |

## Pricing

Prompt caching introduces a tiered pricing structure:

| Model | Base Input | 5m Cache Write | 1h Cache Write | Cache Read |
|---|---|---|---|---|
| Claude Opus 4.7 / 4.6 / 4.5 | $5/MTok | $6.25/MTok | $10/MTok | $0.50/MTok |
| Claude Sonnet 4.6 / 4.5 / 4 | $3/MTok | $3.75/MTok | $6/MTok | $0.30/MTok |
| Claude Haiku 4.5 | $1/MTok | $1.25/MTok | $2/MTok | $0.10/MTok |
| Claude Haiku 3.5 | $0.80/MTok | $1/MTok | $1.6/MTok | $0.08/MTok |

Pricing multipliers:
- 5-minute cache write tokens: 1.25× base input price
- 1-hour cache write tokens: 2× base input price
- Cache read tokens: 0.1× base input price (90% cost reduction)

## Cache Limitations

Minimum cacheable prompt length:
- 4096 tokens: Claude Opus 4.7/4.6/4.5, Claude Haiku 4.5
- 2048 tokens: Claude Sonnet 4.6, Claude Haiku 3.5
- 1024 tokens: Claude Sonnet 4.5/4, Claude Opus 4.1/4, Claude Sonnet 3.7

Shorter prompts are processed without caching and no error is returned. Check `cache_creation_input_tokens` and `cache_read_input_tokens` in the response to confirm caching occurred.

## What Can Be Cached

- Tool definitions in the `tools` array
- System message content blocks
- Text messages (user and assistant turns)
- Images and documents in user turns
- Tool use and tool results

**Cannot be cached:** Thinking blocks (directly), sub-content blocks like citations, empty text blocks.

## Tracking Cache Performance

Response `usage` fields:

- `cache_creation_input_tokens`: Tokens written to cache (new entry created)
- `cache_read_input_tokens`: Tokens retrieved from cache (cache hit)
- `input_tokens`: Tokens after the last cache breakpoint (not eligible for cache)

Total input tokens = `cache_read_input_tokens` + `cache_creation_input_tokens` + `input_tokens`

**Example:** 100,000-token system prompt already cached + 50-token user message:
- `cache_read_input_tokens`: 100,000
- `cache_creation_input_tokens`: 0
- `input_tokens`: 50
- Total: 100,050 tokens processed

## What Invalidates the Cache

Cache follows the hierarchy: `tools` → `system` → `messages`. Changes at each level invalidate that level and all subsequent levels.

| What changes | Impact |
|---|---|
| Tool definitions | Invalidates entire cache |
| Web search / citations toggle | Invalidates system + messages cache |
| Speed setting change | Invalidates system + messages cache |
| `tool_choice` changes | Invalidates messages cache only |
| Images added/removed | Invalidates messages cache only |
| Thinking parameters | Invalidates messages cache only |

## Explicit Cache Breakpoint Mechanics

**Three core principles:**

1. **Cache writes happen only at your breakpoint.** `cache_control` on a block writes exactly one cache entry: a hash of the prefix ending at that block.
2. **Cache reads look backward for prior writes.** On each request, the system walks backward one block at a time checking for matching cache entries.
3. **The lookback window is 20 blocks.** If no matching entry is found in 20 positions, checking stops.

You can define up to **4 cache breakpoints** per request. Use multiple breakpoints when different sections change at different frequencies (e.g., tools rarely change, but context updates daily).

## Caching Tool Definitions

Place `cache_control` on the last tool in your `tools` array. All tools before and including that tool are cached as a single prefix.

```json
{
  "tools": [
    {
      "name": "get_weather",
      "description": "Get the current weather in a given location",
      "input_schema": {"type": "object", "properties": {"location": {"type": "string"}}}
    },
    {
      "name": "get_time",
      "description": "Get the current time in a given time zone",
      "input_schema": {"type": "object", "properties": {"timezone": {"type": "string"}}},
      "cache_control": {"type": "ephemeral"}
    }
  ]
}
```

## 1-Hour Cache Duration

For content used less frequently than every 5 minutes, use the 1-hour TTL:

```json
{"cache_control": {"type": "ephemeral", "ttl": "1h"}}
```

Use 1-hour cache when:
- Agentic tasks take longer than 5 minutes
- Long chat sessions where users may not respond within 5 minutes
- Latency is critical and follow-up prompts may be delayed beyond 5 minutes
- Improving rate limit utilization (cache hits are not deducted against rate limits)

**Constraint when mixing TTLs:** Longer TTL cache entries must appear before shorter TTL entries in the prompt.

## Pre-Warming the Cache

Send a request with `max_tokens: 0` to load content into the cache before real user traffic arrives. This eliminates the cache-miss latency penalty on the first user interaction.

```python
def prewarm_cache() -> None:
    client.messages.create(
        model="claude-opus-4-7",
        max_tokens=0,
        system=SYSTEM_PROMPT,          # has cache_control on last block
        messages=[{"role": "user", "content": "warmup"}],
    )
```

Pre-warm limitations — rejected with `invalid_request_error` when combined with:
- `stream: true`
- Extended thinking enabled
- Structured outputs
- `tool_choice` of type "tool" or "any"
- Inside a Message Batches request

## Best Practices

- Use **automatic caching** for multi-turn conversations — it handles breakpoint management automatically.
- Use **explicit breakpoints** when different sections change at different frequencies.
- Place cached content at the **beginning of the prompt**.
- Place the breakpoint on the **last block that stays identical** across requests.
- For concurrent requests, wait for the first response before sending subsequent requests — a cache entry only becomes available after the first response begins.
- Monitor `cache_read_input_tokens` to track cache hit rate and validate your strategy.

## Use Cases

- **Conversational agents**: Cache system instructions + conversation history to reduce cost per turn
- **Coding assistants**: Keep codebase context or summarized repo in the prompt
- **Large document processing**: Embed entire documents without increasing response latency
- **Detailed instruction sets**: Cache 20+ diverse examples of high-quality answers
- **Agentic tool use**: Cache tool definitions across multiple tool call iterations
- **Knowledge base Q&A**: Cache the entire knowledge base as a prompt prefix

## Cache Storage and Isolation

- Caches are isolated between organizations — different organizations never share caches.
- Cache hits require **100% identical** prompt segments up to and including the cached block.
- Starting February 5, 2026: cache isolation changes from organization-level to workspace-level on the Claude API and Azure AI Foundry.
- Output token generation is unaffected by prompt caching — responses are identical to uncached requests.
