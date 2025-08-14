import os
from fpdf import FPDF
import pandas as pd
from statistics import mode
import unicodedata

INTERPRETATIONS = {
    "temperature_one": "Represents the ambient room temperature. Stable values indicate consistent environmental conditions.",
    "temperature_two": "Represents the machine’s internal temperature. High values, especially above 38°C, may indicate potential overheating risks.",
    "vibration_x": "Measures vibration in the X direction. Abnormal values suggest potential mechanical issues.",
    "vibration_y": "Measures vibration in the Y direction. Deviations may indicate misalignment.",
    "vibration_z": "Measures vibration in the Z direction. High values could indicate operational inefficiencies.",
}


def clean_text(text):
    if isinstance(text, str):
        text = unicodedata.normalize("NFKD", text)
        return text.encode("ascii", "ignore").decode("ascii")
    return text


def calculate_trend(series):
    if len(series) < 2 or series.iloc[0] == 0:
        return "stable", 0.0
    trend_strength = ((series.iloc[-1] - series.iloc[0]) / abs(series.iloc[0])) * 100
    trend_direction = (
        "increasing"
        if trend_strength > 0.2
        else "decreasing" if trend_strength < -0.2 else "stable"
    )
    return trend_direction, round(trend_strength, 2)


def format_stats(name, series: pd.Series) -> str:
    avg = round(series.mean(), 2)
    max_val = round(series.max(), 2)
    min_val = round(series.min(), 2)
    mean_val = round(series.mean(), 2)
    try:
        mode_val = round(mode(series), 2)
    except:
        mode_val = "N/A"

    trend_dir, trend_strength = calculate_trend(series)

    stats = f"""{name}:
Maximum: {max_val}°C, Minimum: {min_val}°C, Average: {avg}°C
Mean: {mean_val}°C, Mode: {mode_val}°C
Trend: {trend_dir} (strength: {trend_strength}%)
"""
    return stats


def generate_pdf_report(
    df: pd.DataFrame, selected_columns: list, filename="sensor_report.pdf"
):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, clean_text("Sensor Summary Report"), ln=True)

    pdf.set_font("helvetica", "", 12)
    summary_line = f"Report based on selected columns: {', '.join(selected_columns)}"
    pdf.multi_cell(0, 10, clean_text(summary_line))

    possible_device_columns = ["device_id", "DeviceID", "id", "ID"]
    device_col = next(
        (col for col in possible_device_columns if col in df.columns), None
    )

    if device_col:
        pdf.set_font("helvetica", "B", 14)
        pdf.cell(
            0,
            10,
            clean_text(f"\n--- Device-wise Analysis by '{device_col}' ---"),
            ln=True,
        )

        for device_value in df[device_col].dropna().unique():
            pdf.set_font("helvetica", "B", 12)
            pdf.cell(0, 10, clean_text(f"\n📟 Device: {device_value}"), ln=True)

            device_df = df[df[device_col] == device_value]

            for col in selected_columns:
                if col not in device_df.columns:
                    continue

                pdf.set_font("helvetica", "B", 11)
                pdf.cell(0, 10, clean_text(f"\n↳ Report for '{col}'"), ln=True)

                pdf.set_font("helvetica", "", 11)
                series = device_df[col].dropna()
                if series.empty:
                    pdf.multi_cell(0, 8, "No data available for this column.")
                    continue

                stats = format_stats(col, series)
                pdf.multi_cell(0, 8, clean_text(stats))

                interpretation = INTERPRETATIONS.get(
                    col, "No interpretation available."
                )
                pdf.set_text_color(100, 100, 100)
                pdf.multi_cell(0, 8, clean_text(f"Insight: {interpretation}"))
                pdf.set_text_color(0, 0, 0)
    else:
        pdf.set_font("helvetica", "B", 14)
        pdf.cell(
            0,
            10,
            clean_text(f"\n--- Column-wise Report (No Device ID found) ---"),
            ln=True,
        )

        for col in selected_columns:
            if col not in df.columns:
                continue

            pdf.set_font("helvetica", "B", 12)
            pdf.cell(0, 10, clean_text(f"\nReport for '{col}'"), ln=True)

            pdf.set_font("helvetica", "", 11)
            series = df[col].dropna()
            if series.empty:
                pdf.multi_cell(0, 8, "No data available for this column.")
                continue

            stats = format_stats(col, series)
            pdf.multi_cell(0, 8, clean_text(stats))

            interpretation = INTERPRETATIONS.get(col, "No interpretation available.")
            pdf.set_text_color(100, 100, 100)
            pdf.multi_cell(0, 8, clean_text(f"Insight: {interpretation}"))
            pdf.set_text_color(0, 0, 0)

    os.makedirs("report", exist_ok=True)
    save_path = os.path.join("report", filename)
    pdf.output(save_path)
    return save_path
