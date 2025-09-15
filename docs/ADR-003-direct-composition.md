# ADR-003: Simple Direct Composition

**Date:** 2025-09-15  
**Author:** CServinL

## Context

Our simplified literature review system has only 4 core components (Coordinator, Search Agent, Analysis Agent, Report Agent) that work together in a linear pipeline. We need a straightforward way to wire these components together without over-engineering.

## Decision

Use **direct composition** with no dependency injection, registries, or complex wiring:

### Implementation Approach
- Components are instantiated directly in the Coordinator
- Configuration is passed as parameters to component constructors
- No abstract interfaces or dependency injection frameworks
- Each component is a simple Python class with clear methods

### Example Structure
```python
class Coordinator:
    def __init__(self, config):
        self.search_agent = SearchAgent(config.sources)
        self.analysis_agent = AnalysisAgent(config.execution)
        self.report_agent = ReportAgent(config.output)
    
    def run_review(self):
        papers = self.search_agent.search(self.config.research.topic)
        analysis = self.analysis_agent.analyze(papers)
        report = self.report_agent.generate(analysis)
        return report
```

## Benefits
- **Ultra-simple**: No frameworks or patterns to learn
- **Fast development**: Direct instantiation is quick to implement
- **Easy debugging**: Clear call stack and data flow
- **No magic**: Everything is explicit and visible

## Trade-offs
- **Less flexible**: Changes require code modifications
- **Limited testability**: Harder to mock dependencies without interfaces
- **Not suitable for complex systems**: Works for simple 4-component pipeline

## Rationale
For our Phase 0 MVP with 4 components in a linear pipeline, direct composition is the simplest approach that gets us working software quickly. We can add abstraction layers later if the system grows in complexity.

## When to Revisit
- If we add more than 8-10 components
- If we need complex configuration-driven behavior
- If testing becomes difficult due to tight coupling
- If we need runtime component swapping  
**Author**: Development Team  
**Reviewers**: Architecture Review Board
