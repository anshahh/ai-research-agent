"""
Agent core: planner-executor loop.

Purpose: given a goal, break it into steps, execute each step (calling a
tool if needed), track state, and when a step fails — retry it, and if it
still fails after max_attempts, mark it skipped and move on rather than
crashing the whole run. This is the behavior worth demoing: kill a tool
mid-run and watch it degrade gracefully instead of dying.
"""

import logging
from typing import Callable, Optional

from src.llm_client import LLMClient
from src.state import AgentState, StepStatus
from src.tools.web_search import web_search, ToolError
from src.tools.fetch_page import fetch_page

logger = logging.getLogger("agent")

PLANNER_SYSTEM_PROMPT = """You break a research goal into 2-4 concrete steps.
Each step should be a single, self-contained action.

You have two tools available:
- web_search: search the web for pages related to a query
- fetch_page: fetch and read the full content of one specific URL you already have

Most plans should start with web_search steps to find sources. Only use
fetch_page for a step if you already know a specific URL to read deeply.

Output ONLY a list, one step per line, in this exact format:
TOOL: <web_search or fetch_page> | STEP: <description>

Example:
TOOL: web_search | STEP: Search for Anthropic's latest funding round
TOOL: web_search | STEP: Search for Anthropic's current employee count
"""

# Maps a tool name to its callable. Add new tools here as you build them.
TOOL_REGISTRY: dict[str, Callable] = {
    "web_search": web_search,
    "fetch_page": fetch_page,
}


class Agent:
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client or LLMClient()

    def plan(self, goal: str) -> AgentState:
        """Ask the model to break the goal into steps AND choose a tool per step."""
        response = self.llm.call(
            system=PLANNER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": goal}],
            max_tokens=300,
        )
        state = AgentState(goal=goal)
        for line in response.text.strip().splitlines():
            line = line.strip()
            if not line or "TOOL:" not in line or "STEP:" not in line:
                continue
            try:
                tool_part, step_part = line.split("|", 1)
                tool = tool_part.replace("TOOL:", "").strip()
                description = step_part.replace("STEP:", "").strip()
                if tool in TOOL_REGISTRY and description:
                    state.add_step(description=description, tool=tool)
            except ValueError:
                logger.warning("Couldn't parse planner line: %s", line)
        logger.info("Planned %d steps for goal: %s", len(state.steps), goal)
        return state

    def execute_step(self, state: AgentState, step) -> bool:
        """
        Run a single step. Returns True if it succeeded, False if it
        exhausted retries and had to be skipped. Never raises — failure
        is handled here, not left for the caller to catch.
        """
        step.status = StepStatus.IN_PROGRESS
        tool_fn = TOOL_REGISTRY.get(step.tool)

        while step.attempts < step.max_attempts:
            step.attempts += 1
            try:
                if tool_fn is None:
                    raise ToolError(f"Unknown tool: {step.tool}")

                results = tool_fn(step.description)
                step.result = f"{len(results)} result(s) found"
                step.status = StepStatus.DONE
                for r in results:
                    state.record_evidence(step.id, source=r.url, content=r.text if hasattr(r, "text") else r.snippet)
                logger.info("Step %s succeeded on attempt %d", step.id, step.attempts)
                return True

            except ToolError as e:
                step.error = str(e)
                logger.warning(
                    "Step %s failed (attempt %d/%d): %s",
                    step.id, step.attempts, step.max_attempts, e,
                )

        # Exhausted retries — degrade gracefully instead of crashing the run.
        step.status = StepStatus.SKIPPED
        logger.error(
            "Step %s exhausted %d attempts, skipping. Last error: %s",
            step.id, step.max_attempts, step.error,
        )
        return False

    def run(self, goal: str, save_path: str = "run_state.json", use_db: bool = True) -> AgentState:
        """Full run: plan, then execute every step, saving state after each one."""
        state = self.plan(goal)
        state.save(save_path)
        if use_db:
            state.save_to_db()

        while (step := state.next_pending_step()) is not None:
            self.execute_step(state, step)
            state.save(save_path)
            if use_db:
                state.save_to_db()

        logger.info("Run complete.\n%s", state.summary())
        return state


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    agent = Agent()
    final_state = agent.run("Research the company Anthropic: funding, headcount, recent news")
    print("\n--- FINAL STATE ---")
    print(final_state.summary())
