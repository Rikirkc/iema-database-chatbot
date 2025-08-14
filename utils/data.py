import os
import venv
from pathlib import Path
import streamlit as st
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import ModelInfo
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from autogen_agentchat.agents import AssistantAgent, CodeExecutorAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_core import CancellationToken
from autogen_core.code_executor import CodeBlock
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.base import TaskResult


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORK_DIR = PROJECT_ROOT / "temp"
WORK_DIR.mkdir(parents=True, exist_ok=True)


GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
SKIP_VENV = os.getenv("SKIP_VENV", "1") == "1"
DEFAULT_PIP_PKGS = "openpyxl pandas numpy matplotlib scipy"


async def team_config(run_dir: Path):
    """
    Create a team tied to a specific run_dir (Path).
    run_dir should already exist (app creates it) and contain dataset files copied in.
    """
    model = OpenAIChatCompletionClient(
        model="gemini-2.5-pro",
        model_info=ModelInfo(
            vision=False,
            json_output=False,
            structured_output=False,
            function_calling=True,
            family="gemini-2.5-pro",
        ),
        api_key=GEMINI_API_KEY,
        temperature=0.1,
    )

    venv_context = None
    if not SKIP_VENV:
        try:
            venv_dir = WORK_DIR / ".venv"
            if not venv_dir.exists():
                venv.EnvBuilder(with_pip=True).create(venv_dir)

            builder = venv.EnvBuilder(with_pip=True)
            venv_context = getattr(builder, "ensure_directories", lambda p: None)(
                venv_dir
            )
        except Exception as e:
            print("Warning: venv creation failed or not supported:", e)
            venv_context = None

    local_executor = LocalCommandLineCodeExecutor(
        work_dir=run_dir,
        virtual_env_context=venv_context,
    )

    if not SKIP_VENV and venv_context is not None:
        try:
            await local_executor.execute_code_blocks(
                code_blocks=[
                    CodeBlock(language="bash", code=f"pip install {DEFAULT_PIP_PKGS}")
                ],
                cancellation_token=CancellationToken(),
            )
        except Exception as e:
            print("Warning: pip install in venv failed:", e)

    developer = AssistantAgent(
        name="code_developer",
        model_client=model,
        system_message=(
            "You are a code developer agent. You will be given a csv, tsv, xlsx, xls, json or db file and a question about it. "
            "You can use Python code to answer the question. "
            "Make sure the code is wrapped in a code block with ```python``` language tag to make sure it's executable. THIS IS MANDATORY.\n"
            "When asked to detect anomalies, please:\n"
            "    - Auto-detect thresholds or suggest the best model.\n"
            "    - Output the plan, then code, confirm execution, and output results.\n"
            "    - Use structured output mode in JSON via json_output to return: "
            "{'anomaly_ranges': [List[TimeRange]], 'method': str, 'suggested_threshold': float}.\n"
            "    - Never multiply or scale column values unless explicitly asked. Always plot raw values as-is.\n"
            "    - Always begin with your plan to answer the question. Then write the code to answer it.\n"
            "    - Always write the code in a code block with language(python) specified.\n"
            "    - If you need several code blocks, write one code block at a time.\n"
            "    - You will be working with a code executor agent. Once you write a code block, "
            "you must wait for the code executor to execute it. If the code is executed successfully, you can continue.\n"
            "    - Use pandas to answer the question if possible. If a library is not installed, "
            "use pip install via Python’s subprocess library.\n"
            "    - If asked to plot, use matplotlib and save the plot as a PNG file.\n"
            "      After successful execution, say exactly: GENERATED:<filename> (e.g., GENERATED:plot.png) in a new line.\n"
            "    - Once results are ready, provide the final answer, and then say exactly 'TERMINATE'.\n"
            "    - NEVER terminate until the code is executed by the code executor and the answer is ready.\n\n"
            "When asked to compare or analyze behavioral patterns across devices or sensors, follow this guideline:\n"
            "1. Automatically detect the identifier column like 'device_id', 'id', or similar.\n"
            "2. Group data by each device.\n"
            "3. For each device, compute descriptive statistics (mean, std, min, max) for all key sensor columns like temperature, vibration, gyroscope.\n"
            "4. Make sure that, if you don't find any column names, you add a check to see if there are any columns which are similar and then use them as final.\n"
            "5. Additionally compute trend analysis using:\n"
            "   - Simple Moving Average (SMA) to observe smoothed behavior over time\n"
            "   - Exponential Moving Average (EMA) to detect recent spikes or drops more sensitively\n"
            "6. Identify patterns — e.g., which device runs hotter, which is cooler, which has more vibration, which has stable gyro, etc.\n"
            "7. Use natural language to summarize:\n"
            "   - Mention average behavior per device\n"
            "   - Mention extreme behaviors (e.g., highest tem          perature)\n"
            "   - Mention possible reasons (workload, mounting, orientation, time)\n"
            "   - Mention Anomalies if present using Extreme Value Theory (EVT) or Peaks Over Threshold (POT) methods. \n"
            "   - Highlight both similarities and differences\n"
            "   - If there's need for looking for anomalies use EVT to calculate. Don't use machine learning or such methods as they are compute heavy."
            "8. Present final output as a high-level summary, like:\n\n"
            "Summary of Differences:\n"
            "The two devices exhibit distinct behavioral patterns...\n"
            "Device A tends to run hotter...\n"
            "Device B shows more vibration...\n"
            "These differences could be due to...\n"
            "Do NOT just give metrics — always explain the patterns with reasoning and use terms like 'hotter', 'cooler', 'more stable', 'more variation'.\n"
            "Use pandas to compute values, matplotlib only if asked to plot.\n"
            "If needed, generate intermediate code block, then provide final output.\n"
            "NEVER terminate until the code is executed and final summary is ready."
            "9. ABSOLUTELY MAKE SURE TO EXECUTE THE CODE BEFORE TERMINATING. IF YOU DON'T EXECUTE THE CODE BEFORE TERMINATING THERE WILL BE HUGE ALTERING CONSEQUENCES."
        ),
    )

    executor = CodeExecutorAgent(
        name="code_executor",
        code_executor=local_executor,
    )

    team = RoundRobinGroupChat(
        participants=[developer, executor],
        termination_condition=TextMentionTermination("TERMINATE"),
        max_turns=20,
    )

    return team, local_executor


async def orchestrate(
    team: RoundRobinGroupChat, local_executor: LocalCommandLineCodeExecutor, task: str
):
    """
    Run team.run_stream and yield messages as before.
    Caller is responsible for creating and cleaning up run_dir.
    """
    try:
        await local_executor.start()
    except Exception as e:
        print("Executor failed to start:", e)
        raise

    try:
        async for message in team.run_stream(
            task=task, cancellation_token=CancellationToken()
        ):
            if isinstance(message, TextMessage):
                print(msg := f"{message.source}: {message.content}")
                yield msg
            elif isinstance(message, TaskResult):
                print(msg := f"Stopping reason: {message.stop_reason}")
                yield msg
    finally:
        try:
            await local_executor.stop()
        except Exception as e:
            print("Failed to stop executor cleanly:", e)
