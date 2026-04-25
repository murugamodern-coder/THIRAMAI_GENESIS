"""
LLM clients and routing layer for Thiramai Sovereign OS.

Submodules:
- :mod:`services.llm.local_llama` — local Ollama client + smart router
  (simple → local, complex → Groq, research → Tavily + Groq).
"""
