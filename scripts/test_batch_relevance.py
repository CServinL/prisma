"""Quick experiment: batch relevance check in a single LLM call."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from prisma.agents.analysis_agent import AnalysisAgent

QUERY = "super resolution image reconstruction"

CANDIDATES = [
    ("A", "Real-ESRGAN: Training Real-World Blind Super-Resolution with Pure Synthetic Data"),
    ("B", "Attention is All You Need"),
    ("C", "SRCNN: Image Super-Resolution Using Deep Convolutional Networks"),
    ("D", "Grassmannian quantum cohomology in the infinite limit and total positivity"),
    ("E", "Blind Image Super-Resolution via Contrastive Representation Learning"),
    ("F", "T-Rex: Tactile-Reactive Dexterous Manipulation"),
    ("G", "Perceptual Losses for Real-Time Style Transfer and Super-Resolution"),
    ("H", "Consensus-based Agentic LLM Framework for Harmonized Tariff Schedule Classification"),
    ("I", "Neural Network Approaches to Single Image Super-Resolution: A Survey"),
    ("J", "Seeing Through Circuits: Faithful Mechanistic Interpretability for Vision Transformers"),
]

agent = AnalysisAgent()
print(f"Topic: {QUERY!r}")
print(f"Sending {len(CANDIDATES)} candidates in one LLM call...\n")

flags = agent.batch_relevance_check(QUERY, CANDIDATES)

print("Results:")
for (key, title), relevant in zip(CANDIDATES, flags):
    marker = "YES" if relevant else " no"
    print(f"  [{marker}] {key}. {title}")
