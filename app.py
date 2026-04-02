import streamlit as st
import pdfplumber
import pandas as pd
import re
from pdfrw import PdfReader, PdfWriter

st.set_page_config(page_title="B/L Tool", layout="wide")

st.title("🚢 BILL OF LADING AUTOMATION")

pdf_file = st.file_uploader("📄 Upload SI PDF", type=["pdf"])
excel_file = st.file_uploader("📊 Upload DATA Excel", type=["xlsx"])


# ===== EXTRACT TEXT =====
def extract_text(pdf):
    with pdfplumber.open(pdf) as p:
        return " ".join([page.extract_text() for page in p.pages])


# ===== PARSE =====
def parse(text):
    data = {}

    # ===== CONSIGNEE =====
    m = re.search(r"Consigned to\s*:\s*(.*?)\s+Notify", text)
    data["consignee"] = m.group(1).strip() if m else ""

    # ===== POD =====
    m = re.search(r"To\s*:\s*(.+?)PORT", text)
    data["pod"] = m.group(1).strip() if m else ""

    # ===== CONTAINER =====
    m = re.search(r"CONTAINER No/SEAL No\s*:\s*(\S+)/(\S+)", text)
    if m:
        data["container"] = m.group(1)
        data["seal"] = m.group(2)
    else:
        data["container"] = ""
        data["seal"] = ""

    # ===== VESSEL + VOYAGE =====
    m = re.search(r"VESSEL'S NAME:\s*(.*?)\s", text)
    vessel_full = m.group(1).strip() if m else ""

    parts = vessel_full.split()
    if len(parts) > 1:
        data["voyage"] = parts[-1]
        data["ocean_vessel"] = " ".join(parts[:-1])
    else:
        data["ocean_vessel"] = vessel_full
        data["voyage"] = ""

    # ===== ETD =====
    m = re.search(r"ETD:\s*([A-Za-z]+\s\d{2},\s\d{4})", text)
    data["etd"] = m.group(1) if m else ""

    # ===== GOODS (CLEAN) =====
    m = re.search(r"M3\s+(.*?)\s+TOTAL", text)
    if m:
        goods = m.group(1)
        goods = re.sub(r"\s+", " ", goods)
        data["goods"] = goods.strip()
    else:
        data["goods"] = ""

    # ===== TOTAL =====
    total_match = re.search(
        r"TOTAL\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+([\d\.]+)",
        text
    )

    if total_match:
        data["packages"] = total_match.group(1)
        data["gross"] = total_match.group(4)
        data["cbm"] = total_match.group(5)
    else:
        data["packages"] = "0"
        data["gross"] = "0"
        data["cbm"] = "0"

    return data


# ===== FILL PDF =====
def fill_pdf(data):
    template = PdfReader("template.pdf")

    for page in template.pages:
        if hasattr(page, "Annots") and page.Annots:
            for annot in page.Annots:
                if annot.T:
                    key = annot.T[1:-1]

                    if key in data:
                        annot.V = str(data[key])
                        annot.AP = None

    output = "BL_output.pdf"
    PdfWriter().write(output, template)
    return output


# ===== RUN =====
if pdf_file and excel_file:

    text = extract_text(pdf_file)
    data = parse(text)

    df = pd.read_excel(excel_file)

    # chuẩn hóa cột excel
    df.columns = df.columns.str.strip().str.upper()

    st.subheader("📋 Extracted Data")
    st.json(data)

    container = data.get("container", "")

    if container == "":
        st.error("❌ Không đọc được container")
    else:
        match = df[df.apply(lambda r: container in str(r), axis=1)]

        if not match.empty:

            row = match.iloc[0]

            # ===== LẤY HBL NO =====
            data["bl_no"] = str(row.get("HBL NO", "NO_BL"))

            st.success("✅ Match DATA + Lấy HBL NO")

            if st.button("📤 TẠO BILL (PDF)"):

                pdf_file = fill_pdf(data)

                with open(pdf_file, "rb") as f:
                    st.download_button(
                        "⬇️ Download B/L PDF",
                        f,
                        file_name=data["bl_no"] + ".pdf"
                    )

        else:
            st.error("❌ Không match Excel")
