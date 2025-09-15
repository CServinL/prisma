# ADR-005: Simple Sequential Processing

**Date:** 2025-09-15  
**Author:** CServinL

## Context

Our literature review system uses a simple 4-component pipeline (Coordinator → Search Agent → Analysis Agent → Report Agent). We need to determine how these components communicate and coordinate their work.

## Decision

Use **direct sequential function calls** with no complex messaging or async coordination:

### Communication Approach
- **Sequential Processing**: Each component completes its work before the next begins
- **Direct Function Calls**: Components call each other's methods directly
- **Shared Data Structures**: Results passed as Python objects between components
- **Simple Progress Tracking**: Coordinator updates job status in SQLite database

### Implementation
```python
class Coordinator:
    def run_review(self, config):
        # Update status: Starting search
        self.update_job_status("searching")
        papers = self.search_agent.search(config.research.topic)
        
        # Update status: Analyzing papers  
        self.update_job_status("analyzing")
        analysis = self.analysis_agent.analyze(papers)
        
        # Update status: Generating report
        self.update_job_status("reporting")
        report = self.report_agent.generate(analysis)
        
        # Update status: Completed
        self.update_job_status("completed")
        return report
```

## Benefits
- **Ultra-simple**: No message queues, brokers, or async complexity
- **Easy to debug**: Linear execution with clear call stack
- **Reliable**: Fewer moving parts means fewer failure points
- **Fast development**: No async/await complexity to manage

## Trade-offs
- **No parallelism**: Components run one at a time
- **Blocking**: Long-running operations block the entire pipeline
- **Limited scalability**: Cannot process multiple papers simultaneously

## Why This Approach?
For Phase 0 MVP, simplicity trumps performance. We can:
1. Get working software quickly
2. Understand the real performance bottlenecks
3. Add parallelism in Phase 1 where it actually matters

## Future Considerations
- **Phase 1**: Add async processing within components (e.g., parallel paper analysis)
- **Phase 2**: Consider message queues if we need true distributed processing
- **Performance monitoring**: Measure where time is actually spent before optimizing
```

#### Workflow Coordination Messages
```python
# Job initialization
{
    "type": "job_start",
    "job_id": "lit_review_123",
    "workflow": "literature_review",
    "config": {
        "research_query": "machine learning interpretability healthcare",
        "agents": ["search", "processing", "synthesis"],
        "parallel_tasks": 3
    }
}

# Cross-agent data sharing
## Implementation Notes

### Current State (Phase 0)
- All processing happens in a single thread
- Job status updates stored in SQLite database
- CLI can query job status via database polling
- No real-time updates during execution

### Error Handling
- Simple try/catch blocks around each component
- Failed jobs marked as "error" state in database
- Error messages and stack traces logged for debugging

### Progress Tracking
Job status states:
- `queued`: Job submitted but not started
- `searching`: Searching for papers
- `analyzing`: Analyzing and summarizing papers
- `reporting`: Generating final report
- `completed`: Job finished successfully
- `error`: Job failed with error

## When to Reconsider
- If search or analysis takes longer than 10-15 minutes
- If we need to process multiple jobs simultaneously
- If users request real-time progress updates
- If we add collaborative features that need live updates

---

**Related ADRs**: 
- [ADR-001: Simple Pipeline Architecture](./ADR-001-simple-pipeline-architecture.md)
- [ADR-003: Direct Composition](./ADR-003-direct-composition.md)
```

### Agent Communication Flow

#### 1. Job Initialization
```python
# Coordinator receives literature review request
job = LiteratureReviewJob(
    query="machine learning interpretability healthcare",
    config=research_config
)

# Coordinator creates task graph
tasks = [
    SearchTask(databases=["pubmed", "arxiv"]),
    ProcessingTask(depends_on=["search"]),
    SynthesisTask(depends_on=["processing"])
]

# Distribute initial tasks to available agents
await coordinator.distribute_tasks(tasks)
```

#### 2. Agent Task Processing
```python
# Search agent receives task
@agent.handle("search_task")
async def handle_search(task_message):
    results = await search_papers(task_message.payload)
    
    # Send progress updates
    await coordinator.send_progress(
        task_id=task_message.task_id,
        progress={"completed": len(results), "total": estimated_total}
    )
    
    # Complete task and trigger next stage
    await coordinator.send_completion(
        task_id=task_message.task_id,
        results=results,
        next_tasks=["processing_task"]
    )
```

#### 3. Result Aggregation
```python
# Coordinator aggregates results from multiple agents
@coordinator.handle("task_complete")
async def handle_completion(completion_message):
    job = self.get_job(completion_message.job_id)
    job.update_progress(completion_message)
    
    # Check if workflow stage is complete
    if job.stage_complete("search"):
        # Trigger next stage
        processing_tasks = job.create_processing_tasks()
        await self.distribute_tasks(processing_tasks)
    
    # Update job status for CLI polling
    await self.update_job_status(job)
```

### Communication Patterns

#### 1. Pipeline Pattern (Sequential Stages)
```
Search Agent → Processing Agent → Synthesis Agent
     ↓              ↓                ↓
  Papers →       Analyzed →      Final Report
                  Data
```

#### 2. Fan-Out/Fan-In Pattern (Parallel Processing)
```
                Search Agent
                     ↓
         ┌───── Processing Agent 1 ─────┐
         │                              │
         ├───── Processing Agent 2 ─────┤ → Synthesis Agent
         │                              │
         └───── Processing Agent 3 ─────┘
```

#### 3. Event-Driven Pattern (Reactive Processing)
```
Any Agent → Event → Coordinator → Interested Agents
    ↓                               ↓
Status Update              Reactive Tasks
```

## Technical Implementation

### Message Queue Implementation
```python
# src/orchestrator/message_passing.py
class AsyncMessageQueue:
    def __init__(self):
        self.queues = {}  # agent_id -> asyncio.Queue
        self.subscribers = {}  # event_type -> [agent_ids]
    
    async def send_message(self, agent_id: str, message: dict):
        if agent_id in self.queues:
            await self.queues[agent_id].put(message)
    
    async def broadcast_event(self, event_type: str, event_data: dict):
        for agent_id in self.subscribers.get(event_type, []):
            await self.send_message(agent_id, {
                "type": event_type,
                "data": event_data
            })
```

### Agent Registration
```python
# src/orchestrator/coordinator.py  
class WorkflowCoordinator:
    def __init__(self):
        self.agents = {}  # agent_id -> agent_info
        self.jobs = {}    # job_id -> job_state
        self.message_queue = AsyncMessageQueue()
    
    async def register_agent(self, agent_id: str, capabilities: list):
        self.agents[agent_id] = {
            "capabilities": capabilities,
            "status": "available",
            "last_heartbeat": datetime.now()
        }
        
        # Create message queue for agent
        self.message_queue.create_queue(agent_id)
```

### Error Handling and Recovery
```python
# Retry mechanism for failed tasks
class TaskRetryHandler:
    async def handle_task_failure(self, task_id: str, error: dict):
        task = self.get_task(task_id)
        
        if error.get("recoverable") and task.retry_count < task.max_retries:
            # Exponential backoff retry
            delay = 2 ** task.retry_count
            await asyncio.sleep(delay)
            
            task.retry_count += 1
            await self.redistribute_task(task)
        else:
            # Mark task as failed, attempt graceful degradation
            await self.handle_permanent_failure(task)
```

## Benefits for Literature Review System

### 1. Scalable Parallel Processing
- Multiple agents can process different aspects of literature simultaneously
- Search agents can query multiple databases in parallel
- Processing agents can analyze papers concurrently
- Synthesis agents can work on different sections independently

### 2. Resilient Workflow Execution
- Failed tasks can be retried or redistributed to other agents
- Partial results are preserved even if some agents fail
- Graceful degradation when specific capabilities are unavailable
- Progress tracking allows resuming interrupted literature reviews

### 3. Flexible Agent Specialization
- Search agents specialized for different academic databases
- Processing agents optimized for specific analysis types
- Synthesis agents focused on different output formats
- Easy addition of new agent types without workflow changes

### 4. Efficient Resource Utilization
- Agents only process tasks matching their capabilities
- Work distribution based on agent availability and load
- Async communication prevents blocking on slow operations
- Memory-efficient streaming of large literature datasets

## Alternative Approaches and Phase 0 Choice

### 1. CLI Polling for Status (Chosen for Phase 0)
- **Pros**: Simple, aligns with batch workflows, no background connections
- **Cons**: Status freshness depends on polling interval
- **Verdict**: Selected for Phase 0. Keeps system simple and robust.

### 2. External Message Broker (Redis/RabbitMQ)
- **Pros**: Durable queues, cross-process/distributed scaling
- **Cons**: Extra infrastructure and ops overhead
- **Verdict**: Deferred to later phases if scaling requires

### 3. WebSockets for Real-Time UI
- **Pros**: Low-latency bidirectional updates to a web client
- **Cons**: Not needed for CLI-first batch workflows; adds complexity
- **Verdict**: Deferred. Revisit if/when a web UI is introduced.

### 4. Server-Sent Events (SSE)
- **Pros**: Simpler than WebSockets for one-way updates
- **Cons**: Still implies a running server; not needed in Phase 0
- **Verdict**: Deferred alongside WebSockets

### 5. Actor Frameworks (Ray/Celery)
- **Pros**: Strong distributed primitives
- **Cons**: Heavyweight for Phase 0 needs
- **Verdict**: Consider in later phases if required

## Risks and Mitigations

### Risk: Message Ordering and Dependencies
- **Mitigation**: Task dependency tracking and sequence numbering
- **Mitigation**: Topological sort for task execution order
- **Mitigation**: Explicit dependency checks before task distribution

### Risk: Agent Failure and Recovery
- **Mitigation**: Health monitoring and automatic task redistribution
- **Mitigation**: Graceful degradation when specific agents unavailable
- **Mitigation**: Partial result preservation for workflow resumption

### Risk: Message Queue Memory Usage
- **Mitigation**: Queue size monitoring and backpressure mechanisms
- **Mitigation**: Message cleanup after successful processing
- **Mitigation**: Spillover to disk for large result datasets

### Risk: Debugging Distributed Workflows
- **Mitigation**: Comprehensive logging with correlation IDs
- **Mitigation**: Message tracing and workflow visualization tools
- **Mitigation**: Replay capabilities for debugging failed workflows

## Implementation Status (Phase 0)

### ✅ Completed
- In-memory async message queue
- Workflow coordinator with task distribution and aggregation
- Job state store with progress/status accessible to CLI
- Retry handler with exponential backoff
- Unit tests for message routing and coordination logic

### 📊 Test Coverage
- Queue operations: enqueue/dequeue, broadcast
- Coordinator: task distribution, stage completion, aggregation
- Error handling: retries, permanent failures, degradation paths

### 🔧 Configuration
```python
# Orchestration settings (configurable)
POLLING_INTERVAL_SECONDS = 5
MAX_INFLIGHT_TASKS = 100
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2
QUEUE_MAXSIZE = 1000
```

## CLI Integration Guide

- `prisma review status --job-id <id>`: Reads orchestrator job state
- `prisma review results --job-id <id> --format json`: Retrieves final outputs
- `prisma review cancel --job-id <id>`: Requests job cancellation

## Future Enhancements

### Phase 2: Scaling and APIs
- Optional REST API exposing job status for external tooling
- Pluggable external broker (Redis/RabbitMQ) for durability
- Persistence of intermediate messages and results

### Phase 3: Advanced Features
- Cross-process/distributed agent execution
- Priority queues and QoS per agent type
- Optional real-time UI updates via WebSockets (if a web UI is introduced)

## Conclusion

Async in-process message passing with a central coordinator enables efficient, resilient agent collaboration for literature review workflows. For Phase 0, CLI polling provides sufficient visibility without adding server or connection complexity. WebSockets and external brokers are intentionally deferred until a clear need emerges.
