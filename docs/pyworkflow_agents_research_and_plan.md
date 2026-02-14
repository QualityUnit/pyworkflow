# PyWorkflow Agents Module - Research & Phased Implementation Plan

## Executive Summary

This document synthesizes research from 4 parallel investigations into AI agent architectures, covering 15+ frameworks and academic patterns. The goal: build a `pyworkflow_agents` module that brings durable, event-sourced agent orchestration to PyWorkflow -- a capability no existing framework offers.

**Unique value proposition**: PyWorkflow is the only framework that can combine **event-sourced durable execution** with **multi-agent AI orchestration**, enabling deterministic replay, crash recovery, time-travel debugging, and full audit trails for agent decisions.

---

## Part 1: Research Findings

### 1.1 Agent Taxonomies (What Types of Agents Exist)

| Agent Type | Description | Used By |
|------------|-------------|---------|
| **ReAct** | Reasoning + Acting loop (think-observe-act) | LangChain, most frameworks |
| **Tool-Calling** | LLM decides which tools to invoke via function calling | Claude, OpenAI, all modern LLMs |
| **Plan-and-Execute** | Separate planning phase, then execution phase | Claude Code plan mode, LangGraph |
| **Multi-Agent Supervisor** | Central orchestrator delegates to specialized workers | CrewAI, LangGraph, Claude Code teams |
| **Multi-Agent Swarm** | Peers coordinate via explicit handoffs, no central controller | OpenAI Swarm, Claude Code teams |
| **Multi-Agent Hierarchical** | Nested supervisor trees with sub-teams | Google ADK, AutoGen |
| **Collaborative/Shared Scratchpad** | All agents share a workspace and see each other's work | LangGraph |
| **Reflection/Self-Correction** | Agent evaluates and improves its own output | LangGraph, Claude Agent SDK |
| **Router/Dispatcher** | Agent routes requests to specialized sub-agents | OpenCode, Claude Code Task tool |
| **RAG Agent** | Retrieval-augmented agent with vector search | LangChain, all frameworks |
| **Code Generation Agent** | Specialized for writing and editing code | Claude Code, OpenCode, Cursor |

### 1.2 Core Patterns Across All Frameworks

#### The Agentic Loop (Universal Pattern)
Every framework implements some variant of:
```
1. Receive task/prompt
2. Gather context (read files, search, retrieve memory)
3. Reason about what to do next
4. Take action (tool call, code edit, API call)
5. Observe result
6. Decide: done? → return result : → go to step 2
```

#### Tool Use Pattern
- **Function Calling**: LLM returns structured tool calls, harness executes them (Claude, OpenAI)
- **MCP (Model Context Protocol)**: Standardized tool integration across providers (Anthropic standard)
- **A2A (Agent-to-Agent Protocol)**: Cross-vendor agent communication (Google standard)

#### Memory Patterns
| Memory Type | Scope | Implementation |
|------------|-------|----------------|
| **Short-term / Working** | Current session | Conversation history in context window |
| **Long-term** | Cross-session | External store (vector DB, file system) |
| **Episodic** | Specific past interactions | Semantic retrieval of past experiences |
| **Procedural** | How to do things | Skills, instructions, CLAUDE.md |

#### Orchestration Patterns
| Pattern | Description | Best For |
|---------|-------------|----------|
| **Sequential** | Agent A → Agent B → Agent C | Pipeline tasks |
| **Parallel (Scatter-Gather)** | Spawn N agents, collect results | Research, analysis |
| **Graph-Based** | Arbitrary DAG/cyclic graph of agents | Complex coordination |
| **Event-Driven** | Agents react to events | Real-time systems |
| **Hierarchical** | Tree of supervisor → worker agents | Large-scale orchestration |

### 1.3 Framework-Specific Findings

#### LangChain / LangGraph
- **LangGraph** is the modern standard: graph-based agent orchestration with state machines
- Uses **state channels** (deltas, not full history) for efficient multi-agent coordination
- Supports **cyclical workflows** (beyond traditional DAGs) -- crucial for agentic loops
- **Checkpointing** built in: persist state at each node for recovery
- **Human-in-the-loop** via interrupt nodes in the graph
- Key patterns: Supervisor, Collaborative (shared scratchpad), Reflection
- Performance: fastest framework, fewest tokens due to state-delta approach

#### Claude Code / Claude Agent SDK
- **Agentic loop**: Gather context → Take action → Verify results → Iterate
- **Sub-agents (Task tool)**: Spawn specialized agents with isolated context windows
  - Each sub-agent gets fresh context (prevents context bloat)
  - Returns summary to parent (not full conversation)
  - Can be specialized: Explore (read-only), Plan (read-only), general-purpose (full access)
- **Agent Teams**: Full multi-agent coordination
  - Team lead + teammates, each a full Claude Code instance
  - Inbox-based messaging (SendMessage, broadcast)
  - Shared task list with DAG dependencies (TaskCreate, TaskUpdate)
  - Teammates self-claim work, coordinate independently
- **Claude Agent SDK**: Programmatic access to all Claude Code capabilities
  - `query()` API with streaming messages
  - Built-in tools (Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch)
  - Custom sub-agents via `AgentDefinition`
  - Sessions with resume/fork
  - Hooks for lifecycle events (PreToolUse, PostToolUse, Stop, etc.)
  - Permission modes (default, acceptEdits, bypassPermissions, plan, delegate)
- **Multi-Agent Research System** (Anthropic internal):
  - Orchestrator-worker pattern
  - Lead agent spawns 3-5 subagents in parallel
  - Each subagent gets: objective, output format, tool guidance, task boundaries
  - CitationAgent for post-processing
  - 90% performance improvement over single agent
- **Long-Running Agent Harness**:
  - Initializer agent (one-time setup) + Coding agent (incremental progress)
  - State persisted via git commits + progress files
  - Feature list as JSON (200+ items, only pass/fail status changes)
  - Human-engineer-inspired: methodical, incremental, not one-shot

#### OpenCode
- **Multi-agent with role-based specialization**: build (full access), plan (read-only), general (subagent)
- **Provider-agnostic**: works with any LLM
- **LSP integration**: native Language Server Protocol support
- **Client/server architecture**: remote execution with local control

#### CrewAI
- **Crews** (agent teams) + **Flows** (event-driven orchestration) -- dual model
- Hierarchical delegation: manager planner + worker executors
- Standalone (no LangChain dependency)
- Role-based agent specialization with configurable behaviors

#### Microsoft AutoGen → Agent Framework
- Complete redesign in v0.4: async, event-driven
- Converging with Semantic Kernel into unified Microsoft Agent Framework
- Session-based state with checkpoints and versioning
- Graph-based multi-agent orchestration
- Deterministic business workflow patterns (Process Framework)

#### OpenAI Swarm → Agents SDK
- Lightweight, stateless (state externalized)
- Explicit handoff functions between agents
- Clarity and observability over automation
- Evolved into production-ready OpenAI Agents SDK

#### Google ADK
- Code-first, model-agnostic, hierarchical agent composition
- Modular sub-agent design
- Managed deployment via Vertex AI Agent Engine Runtime

#### Vercel AI SDK 6
- Agent-as-interface abstraction (define once, reuse everywhere)
- ToolLoopAgent: production-ready tool execution loop
- Provider-agnostic with type-safe streaming

### 1.4 Key Insight: PyWorkflow's Unique Position

**No existing framework combines event-sourced durable execution with multi-agent AI orchestration.**

| Feature | LangGraph | CrewAI | AutoGen | Claude SDK | **PyWorkflow** |
|---------|-----------|--------|---------|------------|----------------|
| Event sourcing | No | No | No | No | **Yes** |
| Deterministic replay | Checkpoints | No | Checkpoints | Sessions | **Full event replay** |
| Crash recovery | Manual | No | Manual | Resume | **Automatic** |
| Distributed execution | No | No | No | No | **Celery workers** |
| Audit trail | Limited | Limited | Limited | Sessions | **Complete event log** |
| Time-travel debugging | No | No | No | No | **Yes (via events)** |
| Multi-agent | Yes | Yes | Yes | Yes | **Planned** |

This positions `pyworkflow_agents` as **"Durable Agent Orchestration"** -- agents that survive crashes, can be replayed for debugging, produce full audit trails, and scale across distributed workers.

---

## Part 2: Phased Implementation Plan

### Phase 0: Foundation & Provider Abstraction (Week 1-2)
**Goal**: Create the base `pyworkflow_agents` module with LLM provider abstraction.

#### 0.1 Module Structure
```
pyworkflow_agents/
  __init__.py               # Public API
  providers/                # LLM provider abstraction
    __init__.py
    base.py                 # BaseLLMProvider ABC
    anthropic.py            # Claude (Anthropic API)
    openai.py               # OpenAI (GPT-4, etc.)
    types.py                # Message, ToolCall, ToolResult types
  tools/                    # Tool framework
    __init__.py
    base.py                 # BaseTool ABC
    registry.py             # Tool registry
    types.py                # ToolDefinition, ToolResult types
  agent/                    # Core agent
    __init__.py
    base.py                 # BaseAgent ABC + @agent decorator
    loop.py                 # Agentic loop implementation
    types.py                # AgentConfig, AgentResult types
```

#### 0.2 Key Components
- **`BaseLLMProvider`**: Abstract interface for LLM calls
  - `async def generate(messages, tools) -> LLMResponse`
  - `async def generate_stream(messages, tools) -> AsyncIterator[LLMChunk]`
  - Provider implementations: `AnthropicProvider`, `OpenAIProvider`
- **`BaseTool`**: Abstract interface for tools
  - `name`, `description`, `parameters` (JSON Schema)
  - `async def execute(**kwargs) -> ToolResult`
  - `ToolRegistry` for managing available tools
- **`BaseAgent`**: Core agent abstraction
  - Wraps a provider + tools + system prompt
  - `async def run(input, context) -> AgentResult`
  - Integrates with PyWorkflow's `@step` and `@workflow` decorators
- **`@agent` decorator**: Syntactic sugar for defining agents
  ```python
  @agent(provider="anthropic", model="claude-sonnet-4-5-20250929", tools=[search, calculator])
  async def research_agent(query: str):
      """Research agent that finds and summarizes information."""
      pass  # System prompt derived from docstring
  ```

#### 0.3 Event Types (New)
- `AGENT_STARTED` - Agent invocation begins
- `AGENT_TOOL_CALL` - Agent requests a tool call
- `AGENT_TOOL_RESULT` - Tool result returned to agent
- `AGENT_RESPONSE` - Agent produces final response
- `AGENT_COMPLETED` - Agent invocation finishes
- `AGENT_ERROR` - Agent encountered an error

---

### Phase 1: Single Agent with Durable Execution (Week 2-3)
**Goal**: Implement the core agentic loop as a durable PyWorkflow step.

#### 1.1 The Agentic Loop as a Step
```python
@step(name="agent_loop")
async def run_agent(
    agent: BaseAgent,
    input: str,
    max_iterations: int = 20,
) -> AgentResult:
    """Execute agent loop with tool calls, durably recorded."""
    messages = [{"role": "user", "content": input}]

    for i in range(max_iterations):
        response = await agent.provider.generate(messages, agent.tools)

        if response.has_tool_calls:
            for tool_call in response.tool_calls:
                # Each tool call is recorded as an event
                result = await agent.execute_tool(tool_call)
                messages.append(tool_result_message(tool_call, result))
        else:
            return AgentResult(content=response.content, messages=messages)

    return AgentResult(content="Max iterations reached", messages=messages)
```

#### 1.2 Durable Agent Execution
- Each agent invocation = a workflow step (event-sourced)
- Tool calls recorded as `AGENT_TOOL_CALL` / `AGENT_TOOL_RESULT` events
- On replay: tool results replayed from events (no re-execution)
- On crash: resume from last recorded tool result
- Agent state (messages) checkpointed in events

#### 1.3 Agent as Workflow
```python
@workflow(durable=True)
async def agent_workflow(query: str):
    agent = Agent(
        provider=AnthropicProvider(model="claude-sonnet-4-5-20250929"),
        tools=[web_search, file_reader],
        system_prompt="You are a helpful research assistant.",
    )
    result = await run_agent(agent, query)
    return result
```

#### 1.4 Replay-Safe Tool Execution
- Tool calls are idempotent or cached via event sourcing
- On replay, `AGENT_TOOL_RESULT` events provide cached results
- No re-execution of side-effectful tools during replay
- New tool calls after the replay point execute normally

---

### Phase 2: Memory & Context Management (Week 3-4)
**Goal**: Add short-term, long-term, and episodic memory to agents.

#### 2.1 Module Structure Addition
```
pyworkflow_agents/
  memory/
    __init__.py
    base.py                 # BaseMemory ABC
    conversation.py         # ConversationMemory (short-term)
    summary.py              # SummaryMemory (compressed context)
    persistent.py           # PersistentMemory (cross-session via storage)
    types.py                # MemoryEntry, MemoryQuery types
```

#### 2.2 Key Components
- **`ConversationMemory`**: Current session messages (in-context)
  - Automatic summarization when approaching context limits
  - Maps to PyWorkflow's event log (all messages are events)
- **`PersistentMemory`**: Cross-session memory via PyWorkflow storage backends
  - Stores agent learnings, user preferences, past results
  - Queryable by relevance (semantic search) or recency
  - Backed by PyWorkflow's existing storage (File, Redis, SQLite, PostgreSQL)
- **`SummaryMemory`**: Compressed representation of long conversations
  - LLM-based summarization of conversation history
  - Keeps key decisions and outcomes, drops verbose tool outputs

#### 2.3 Integration with Event Sourcing
- All memory operations recorded as events
- `MEMORY_STORED`, `MEMORY_RETRIEVED`, `MEMORY_UPDATED` event types
- Memory state fully reconstructable from event replay
- Cross-session memory persisted in PyWorkflow storage

---

### Phase 3: Multi-Agent Orchestration (Week 4-6)
**Goal**: Implement supervisor, swarm, and collaborative multi-agent patterns.

#### 3.1 Module Structure Addition
```
pyworkflow_agents/
  orchestration/
    __init__.py
    supervisor.py           # Supervisor pattern (manager + workers)
    swarm.py                # Swarm pattern (peer handoffs)
    parallel.py             # Parallel agent execution (scatter-gather)
    sequential.py           # Sequential agent pipeline
    types.py                # HandoffResult, AgentTeam types
```

#### 3.2 Supervisor Pattern
A lead agent orchestrates specialized worker agents.

```python
@workflow(durable=True)
async def research_with_supervisor(topic: str):
    supervisor = SupervisorAgent(
        provider=AnthropicProvider(model="claude-sonnet-4-5-20250929"),
        workers=[
            Agent(name="researcher", tools=[web_search], system_prompt="..."),
            Agent(name="analyst", tools=[calculator, chart], system_prompt="..."),
            Agent(name="writer", tools=[file_writer], system_prompt="..."),
        ],
        strategy="sequential",  # or "parallel", "adaptive"
    )
    result = await supervisor.run(f"Research and write a report on: {topic}")
    return result
```

**Implementation**:
- Supervisor = workflow, each worker = step
- Supervisor decides which worker to invoke next
- Worker results feed back to supervisor for next decision
- All orchestration decisions recorded as events
- On crash: supervisor replays events, resumes at last decision point

#### 3.3 Swarm Pattern (Peer Handoffs)
Agents hand off control to each other via explicit handoff functions.

```python
@agent(name="triage")
async def triage_agent(request: str):
    """Analyze request and route to appropriate agent."""
    # Returns handoff instruction
    pass

@agent(name="billing")
async def billing_agent(request: str):
    """Handle billing inquiries."""
    pass

swarm = AgentSwarm(
    agents=[triage_agent, billing_agent, support_agent],
    entry_agent="triage",
)
result = await swarm.run("I have a question about my invoice")
```

**Implementation**:
- Handoff = starting a child workflow for the target agent
- Handoff chain recorded as events (`AGENT_HANDOFF` event type)
- Uses PyWorkflow's `start_child_workflow()` under the hood
- Handoff context passed via workflow arguments

#### 3.4 Parallel Execution (Scatter-Gather)
Multiple agents work simultaneously on different aspects.

```python
@workflow(durable=True)
async def parallel_research(topic: str):
    agents = [
        Agent(name="academic", tools=[arxiv_search]),
        Agent(name="news", tools=[news_search]),
        Agent(name="code", tools=[github_search]),
    ]

    # Scatter: launch all agents in parallel
    results = await parallel_agents(agents, topic)

    # Gather: synthesize results
    synthesis = await synthesize_agent.run(results)
    return synthesis
```

**Implementation**:
- Uses PyWorkflow's existing parallel step execution
- Each agent = a step dispatched to Celery workers
- Results gathered and passed to synthesis agent
- All recorded as events for replay

#### 3.5 Sequential Pipeline
Agents execute in order, each receiving the previous agent's output.

```python
pipeline = AgentPipeline([
    Agent(name="extractor", ...),    # Extract key info
    Agent(name="validator", ...),    # Validate extracted data
    Agent(name="formatter", ...),    # Format for output
])
result = await pipeline.run(raw_input)
```

---

### Phase 4: Advanced Patterns (Week 6-8)
**Goal**: Implement reflection, human-in-the-loop, and guardrails.

#### 4.1 Reflection Pattern
Agent evaluates and improves its own output.

```python
@workflow(durable=True)
async def reflective_coding(task: str):
    agent = ReflectiveAgent(
        generator=Agent(name="coder", ...),
        evaluator=Agent(name="reviewer", ...),
        max_reflections=3,
    )
    result = await agent.run(task)
    return result
```

**Implementation**:
- Generator produces output
- Evaluator critiques it
- Generator revises based on critique
- Loop until evaluator approves or max iterations
- Each reflection cycle = event-sourced step
- Reflection history available for debugging

#### 4.2 Human-in-the-Loop
Agent suspends for human input using PyWorkflow's hook primitive.

```python
@workflow(durable=True)
async def agent_with_approval(task: str):
    # Agent generates a plan
    plan = await planning_agent.run(task)

    # Suspend workflow, wait for human approval via webhook
    approval = await hook("approval", schema=ApprovalSchema, timeout="24h")

    if approval.approved:
        result = await execution_agent.run(plan)
        return result
    else:
        return {"status": "rejected", "reason": approval.reason}
```

**Implementation**:
- Leverages PyWorkflow's existing `hook()` primitive
- Agent suspends, workflow frees resources
- Human reviews via webhook/API
- Workflow resumes with human input
- All recorded as events

#### 4.3 Guardrails & Safety
Input/output validation for agent responses.

```python
agent = Agent(
    provider=AnthropicProvider(...),
    guardrails=[
        InputGuardrail(validator=content_policy_check),
        OutputGuardrail(validator=pii_detector),
        ToolGuardrail(allowed_tools=["search", "read"], blocked_tools=["delete"]),
    ],
)
```

**Implementation**:
- Pre-execution guardrails: validate input before agent processes
- Post-execution guardrails: validate output before returning
- Tool guardrails: restrict which tools agent can use
- Guardrail violations recorded as events
- Configurable: block, warn, or log

---

### Phase 5: Agent SDK & Developer Experience (Week 8-10)
**Goal**: Create a polished developer API with templates and documentation.

#### 5.1 High-Level API
```python
from pyworkflow_agents import Agent, Tool, agent, tool

# Decorator API (simple)
@agent(model="claude-sonnet-4-5-20250929", tools=["web_search"])
async def my_agent(query: str) -> str:
    """A helpful research assistant."""
    pass

# Class API (advanced)
class MyAgent(Agent):
    model = "claude-sonnet-4-5-20250929"
    tools = [web_search, calculator]
    system_prompt = "You are a helpful assistant."
    max_iterations = 20

    async def run(self, query: str) -> str:
        return await self.execute(query)

# Tool definition
@tool
async def web_search(query: str) -> str:
    """Search the web for information."""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.search.com?q={query}")
        return response.text
```

#### 5.2 Pre-built Agent Templates
- **ResearchAgent**: Web search + summarization
- **CodingAgent**: Code generation + testing + review
- **DataAnalysisAgent**: Data loading + analysis + visualization
- **CustomerSupportAgent**: RAG + routing + escalation
- **SupervisorTeam**: Pre-configured supervisor + worker pattern

#### 5.3 Workflow Integration Patterns
```python
# Agent as a workflow step
@workflow(durable=True)
async def process_order(order_id: str):
    # Regular step
    order = await fetch_order(order_id)

    # Agent step (durable, replayable)
    analysis = await analyst_agent.run(f"Analyze order risk: {order}")

    if analysis.risk_level == "high":
        # Human-in-the-loop via hook
        approval = await hook("risk_approval", timeout="1h")
        if not approval.approved:
            return {"status": "rejected"}

    # Continue with regular steps
    result = await process_payment(order_id)
    return result
```

#### 5.4 MCP Integration
```python
from pyworkflow_agents.tools.mcp import MCPToolProvider

# Load tools from MCP servers
mcp_tools = MCPToolProvider(
    servers={
        "github": {"command": "npx", "args": ["@modelcontextprotocol/server-github"]},
        "slack": {"command": "npx", "args": ["@modelcontextprotocol/server-slack"]},
    }
)

agent = Agent(
    provider=AnthropicProvider(...),
    tools=mcp_tools.get_tools(),
)
```

---

### Phase 6: Observability & Production Readiness (Week 10-12)
**Goal**: Agent-specific logging, metrics, tracing, and production features.

#### 6.1 Agent Observability
```
pyworkflow_agents/
  observability/
    __init__.py
    tracing.py              # Agent execution tracing
    metrics.py              # Token usage, latency, tool call metrics
    replay_viewer.py        # Visualize agent replay from events
```

- **Agent Tracing**: Full trace of agent decisions, tool calls, and reasoning
- **Token Metrics**: Track token usage per agent, per step, per workflow
- **Cost Tracking**: Estimated cost per agent invocation
- **Replay Viewer**: CLI tool to replay agent execution from event log
  ```bash
  pyworkflow agents replay <run_id> --step agent_loop
  ```

#### 6.2 Production Features
- **Rate Limiting**: Per-provider, per-agent token/request limits
- **Fallback Providers**: If primary LLM fails, fall back to another
- **Caching**: Cache identical tool calls across agent invocations
- **Timeout Management**: Per-agent, per-tool-call timeouts
- **Retry with Backoff**: Automatic retry for transient LLM errors

---

## Part 3: Implementation Priority Matrix

| Phase | Priority | Complexity | Dependencies | Value |
|-------|----------|------------|-------------|-------|
| Phase 0: Foundation | **Critical** | Medium | None | High - enables everything |
| Phase 1: Single Agent | **Critical** | Medium | Phase 0 | High - core value prop |
| Phase 2: Memory | High | Medium | Phase 1 | Medium - needed for useful agents |
| Phase 3: Multi-Agent | **Critical** | High | Phase 1 | Very High - key differentiator |
| Phase 4: Advanced | Medium | High | Phase 3 | High - production patterns |
| Phase 5: SDK/DX | High | Medium | Phase 1 | High - adoption driver |
| Phase 6: Observability | Medium | Medium | Phase 1 | Medium - production readiness |

**Recommended order**: Phase 0 → Phase 1 → Phase 3 → Phase 5 → Phase 2 → Phase 4 → Phase 6

Rationale: Get the foundation + single agent + multi-agent working first (the core differentiator), then polish the developer experience, add memory, advanced patterns, and observability.

---

## Part 4: Design Principles

1. **Event-First**: Every agent action is an event. This is our differentiator.
2. **Provider-Agnostic**: Support Anthropic, OpenAI, Google, local models from day one.
3. **Dual API**: Both `@agent` decorator (simple) and `Agent` class (advanced), mirroring PyWorkflow's `@workflow`/`Workflow` pattern.
4. **Workflow-Native**: Agents are steps/workflows, not a separate system. They integrate naturally with `sleep()`, `hook()`, `start_child_workflow()`, etc.
5. **Durable by Default**: Agent state survives crashes. Tool results are replayed, not re-executed.
6. **Distributed**: Agents run on Celery workers, scale horizontally.
7. **Observable**: Full trace of every decision, tool call, and outcome.
8. **Composable**: Agents compose into multi-agent systems via the same primitives used for workflow composition.

---

## Sources

### Frameworks Researched
- [LangChain](https://github.com/langchain-ai/langchain) / [LangGraph](https://www.langchain.com/langgraph)
- [Claude Code](https://code.claude.com/docs/en/how-claude-code-works) / [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [OpenCode](https://github.com/anomalyco/opencode)
- [CrewAI](https://www.crewai.com/) / [CrewAI GitHub](https://github.com/crewAIInc/crewAI)
- [Microsoft AutoGen](https://github.com/microsoft/autogen) / [Agent Framework](https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview)
- [OpenAI Swarm](https://github.com/openai/swarm)
- [Google ADK](https://google.github.io/adk-docs/)
- [Vercel AI SDK 6](https://ai-sdk.dev/docs/introduction)
- [Mastra](https://mastra.ai/)

### Key Engineering Posts
- [Anthropic: Building Agents with the Claude Agent SDK](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)
- [Anthropic: How We Built Our Multi-Agent Research System](https://www.anthropic.com/engineering/multi-agent-research-system)
- [Anthropic: Effective Harnesses for Long-Running Agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [Vercel: Workflow Event Sourcing](https://vercel.com/changelog/workflow-event-sourcing)
