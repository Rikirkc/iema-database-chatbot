import re
import shutil
import uuid
import asyncio
from pathlib import Path

import streamlit as st
import pandas as pd

from utils.data import team_config, orchestrate
from utils.report_generator import generate_pdf_report


BASE_DIR = Path(__file__).resolve().parent
TEMP_DIR = BASE_DIR / "temp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


LAST_PLOT_KEY = "last_plot"


DATA_EXTS = {".csv", ".tsv", ".xlsx", ".xls", ".json"}


st.set_page_config(page_title="Talk with your dataset", layout="wide")
st.title("📊 Talk with your Dataset")


def parse_columns(prompt: str):
    col_map = {
        "temp one": "temperature_one",
        "temperature one": "temperature_one",
        "temp1": "temperature_one",
        "temp two": "temperature_two",
        "temperature two": "temperature_two",
        "temp2": "temperature_two",
        "vibration x": "vibration_x",
        "vib x": "vibration_x",
        "vibration y": "vibration_y",
        "vib y": "vibration_y",
        "vibration z": "vibration_z",
        "vib z": "vibration_z",
    }
    prompt_lower = prompt.lower()
    dataset_match = re.search(r"\bdata(\d+)\b", prompt_lower)
    dataset = f"data{dataset_match.group(1)}" if dataset_match else None
    columns = [v for k, v in col_map.items() if k in prompt_lower]
    return columns, dataset


def get_filename_from_msg(msg: str):
    match = re.search(r"GENERATED:([^\s]+\.png)", msg)
    if match:
        return match.group(1)
    return None


def show_message(container, msg: str):
    """Render a single message string produced by orchestrate().
    Show a plot image only when this exact message produced it (GENERATED:<filename>)
    and that filename matches the persistent plot stored in session state.
    """
    with container:

        if msg.startswith("code_developer"):
            with st.chat_message("ai"):
                st.markdown(msg)
        elif msg.startswith("code_executor"):
            with st.chat_message("executor", avatar="🤖"):
                st.markdown(msg)
        elif msg.startswith("Stopping reason:"):
            with st.chat_message("user"):
                st.markdown(msg)
        else:

            with st.chat_message("ai"):
                st.markdown(msg)

        persistent_filename = st.session_state.get("last_plot_filename")
        persistent_path = st.session_state.get(LAST_PLOT_KEY)  # absolute path string

        show_img = False
        if persistent_filename:
            show_img = True
        elif persistent_path:
            try:
                if Path(persistent_path).name:
                    show_img = True
            except Exception:
                pass

        if show_img and persistent_path:
            img_path = Path(persistent_path)
            if img_path.exists():

                with container:
                    st.image(str(img_path), caption=persistent_filename)


uploaded_files = st.file_uploader(
    "Upload your datasets",
    type=list(DATA_EXTS),
    accept_multiple_files=True,
)


if "messages" not in st.session_state:
    st.session_state.messages = []
if LAST_PLOT_KEY not in st.session_state:
    st.session_state[LAST_PLOT_KEY] = None


def clean_temp_keep_persistent_plot():
    persistent_plot = st.session_state.get(LAST_PLOT_KEY)
    persistent_path = Path(persistent_plot) if persistent_plot else None

    for existing_path in TEMP_DIR.iterdir():
        if existing_path.is_file():
            try:
                if persistent_path:
                    try:
                        if existing_path.resolve() == persistent_path.resolve():

                            continue
                    except Exception:
                        if existing_path.name == persistent_path.name:
                            continue
                existing_path.unlink()
            except Exception as e:
                print(f"Could not remove {existing_path}: {e}")


if uploaded_files:
    clean_temp_keep_persistent_plot()

    for idx, file in enumerate(uploaded_files, 1):
        file_extension = Path(file.name).suffix.lower()
        new_path = TEMP_DIR / f"data{idx}{file_extension}"
        with open(new_path, "wb") as f:
            f.write(file.getbuffer())
        st.success(f"✅ File '{file.name}' uploaded as 'data{idx}{file_extension}'.")


chat_container = st.container()
prompt = st.chat_input(
    "Ask a question about your dataset(s)! (e.g., 'columns of data1', 'report for temp one from data2', 'compare columns of all datasets')"
)

if st.session_state.get("messages"):
    for msg in st.session_state["messages"]:
        show_message(chat_container, msg)

plot_path_str = st.session_state.get(LAST_PLOT_KEY)
if plot_path_str:
    plot_path = Path(plot_path_str)
    if plot_path.exists():
        with chat_container:
            st.image(str(plot_path), caption="Last generated plot")

if prompt:
    with chat_container:
        st.write("You asked: ", prompt)


def find_dataset_path(dataset_name: str = None):
    if dataset_name:
        for ext in DATA_EXTS:
            p = TEMP_DIR / f"{dataset_name}{ext}"
            if p.exists():
                return p
        return None

    for p in sorted(TEMP_DIR.iterdir()):
        if p.is_file() and p.name.startswith("data") and p.suffix.lower() in DATA_EXTS:
            return p
    return None


if prompt:

    persistent_plot = st.session_state.get(LAST_PLOT_KEY)
    persistent_path = Path(persistent_plot) if persistent_plot else None
    for p in TEMP_DIR.iterdir():
        if p.is_file() and p.suffix.lower() == ".png":
            try:
                if persistent_path:
                    try:
                        if p.resolve() == persistent_path.resolve():
                            continue
                    except Exception:
                        if p.name == persistent_path.name:
                            continue
                p.unlink()
            except Exception as e:
                print(f"Could not delete {p}: {e}")

    columns_to_report, dataset = parse_columns(prompt)

    if "report" in prompt.lower() and columns_to_report:
        file_path = find_dataset_path(dataset)
        if file_path:

            try:
                if file_path.suffix.lower() == ".csv":
                    df = pd.read_csv(file_path)
                elif file_path.suffix.lower() == ".tsv":
                    df = pd.read_csv(file_path, sep="\t")
                elif file_path.suffix.lower() in {".xlsx", ".xls"}:
                    df = pd.read_excel(file_path)
                elif file_path.suffix.lower() == ".json":
                    df = pd.read_json(file_path)
                else:
                    df = None
            except Exception as e:
                st.error(f"Failed to load dataset: {e}")
                df = None

            if df is not None:
                pdf_path = generate_pdf_report(df, columns_to_report)
                st.success("📄 PDF report generated successfully!")
                with open(pdf_path, "rb") as f:
                    st.download_button(
                        "⬇️ Download Report", f, file_name="sensor_report.pdf"
                    )
        else:
            st.warning("⚠️ Uploaded dataset not found.")
    else:

        async def query():

            run_id = uuid.uuid4().hex
            run_dir = TEMP_DIR / run_id
            run_dir.mkdir(parents=True, exist_ok=True)

            for p in TEMP_DIR.iterdir():
                if p.is_file() and p.name.startswith("data"):
                    try:
                        shutil.copy2(p, run_dir / p.name)
                    except Exception as e:
                        print(f"Warning: could not copy {p} into run_dir: {e}")

            team, local = await team_config(run_dir)

            if "team_state" in st.session_state:
                try:
                    await team.load_state(st.session_state["team_state"])
                except Exception as e:
                    print("Warning: failed to load team state:", e)

            file_paths = [
                str(p)
                for p in run_dir.iterdir()
                if p.is_file()
                and p.name.startswith("data")
                and p.suffix.lower() in DATA_EXTS
            ]
            task = f"{prompt}\nAvailable datasets: {', '.join(file_paths)}"

            non_meta_messages = []

            try:
                with st.spinner("⏳ Processing your request..."):
                    async for msg in orchestrate(team, local, task):

                        if msg.startswith("code_executor") or msg.startswith(
                            "code_developer"
                        ):
                            non_meta_messages.append(msg)
                            if len(non_meta_messages) > 3:
                                non_meta_messages.pop(0)
            finally:

                try:
                    st.session_state["team_state"] = await team.save_state()
                except Exception as e:
                    print("Warning: failed to save team state:", e)

                try:
                    pngs = sorted(
                        run_dir.glob("*.png"), key=lambda p: p.stat().st_mtime
                    )
                    if pngs:
                        latest_png = pngs[-1]
                        dest = TEMP_DIR / f"{run_id}_{latest_png.name}"
                        previous_persistent = st.session_state.get(LAST_PLOT_KEY)
                        previous_path = (
                            Path(previous_persistent) if previous_persistent else None
                        )
                        try:
                            shutil.copy2(latest_png, dest)
                            st.session_state[LAST_PLOT_KEY] = str(dest.resolve())
                            st.session_state["last_plot_filename"] = dest.name
                        except Exception as e:
                            print(
                                "Warning: failed to copy plot to persistent storage:", e
                            )
                        else:
                            # safely remove previous persistent plot after successful copy (if different)
                            try:
                                if (
                                    previous_path
                                    and previous_path.exists()
                                    and previous_path.resolve() != dest.resolve()
                                ):
                                    previous_path.unlink()
                            except Exception as e:
                                print(
                                    "Warning: could not remove previous persistent plot:",
                                    e,
                                )
                except Exception as e:
                    print("Warning while scanning run_dir for PNGs:", e)

                try:
                    await local.stop()
                except Exception:
                    pass

                try:
                    if run_dir.exists() and run_dir.is_dir():
                        shutil.rmtree(run_dir)
                except Exception as e:
                    print("Warning: could not remove run_dir:", e)

            last_developer_msg = next(
                (
                    msg
                    for msg in reversed(non_meta_messages)
                    if msg.startswith("code_developer")
                ),
                None,
            )

            st.session_state["last_code_developer_msg"] = last_developer_msg

            st.session_state.messages = []
            if last_developer_msg:
                st.session_state.messages.append(last_developer_msg)

            for msg in st.session_state.messages:
                show_message(chat_container, msg)

        asyncio.run(query())
