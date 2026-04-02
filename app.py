import streamlit as st
import pdfplumber
import pandas as pd
import re
from datetime import datetime
from supabase import create_client
from pdfrw import PdfReader, PdfWriter

# ===== CONFIG =====
SUPABASE_URL = "https://vicpfbrfodhgwkasrucl.supabase.co"
SUPABASE_KEY = "sb_publishable_0uNjG9GCNulKyJ-J0sPH3g_aw0wip7Z"
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="B/L Tool", layout="wide")

tab1, tab2 = st.tabs(["🚢 Tạo B/L", "📊 Dashboard"])

# =========================
# ===== TAB 1 =====
# =========================
with tab1:

    st.title("🚢 BILL OF LADING AUTOMATION")

    pdf_file = st.file_uploader("📄 Upload SI PDF", type=["pdf"])
    excel_file = st.file_uploader("📊 Upload DATA Excel", type=["xlsx"])

    def extract_text(pdf):
        with pdfplumber.open(pdf) as p:
            return "".join([page.extract_text() for page in p.pages])

    # ===== PARSE CHUẨN =====
    def parse(text):
        data = {}

        # ===== CONSIGNEE =====
        m = re.search(r"Consigned to\s*:\s*\n(.+)", text)
        data["consignee"] = m.group(1).strip() if m else ""

        # ===== POD (cắt trước PORT) =====
        m = re.search(r"To\s*:\s*(.+)", text)
        if m:
            full_pod = m.group(1).strip()
            if "PORT" in full_pod:
                data["pod"] = full_pod.split("PORT")[0].strip()
            else:
                data["pod"] = full_pod.split(",")[0].strip()
        else:
            data["pod"] = ""

        # ===== CONTAINER =====
        m = re.search(r"CONTAINER No/SEAL No\s*:\s*(\S+)/(\S+)", text)
        if m:
            data["container"] = m.group(1)
            data["seal"] = m.group(2)
        else:
            data["container"] = ""
            data["seal"] = ""

        # ===== VESSEL =====
        m = re.search(r"VESSEL'S NAME:\s*(.*?)\n", text)
        vessel_full = m.group(1).strip() if m else ""

        match = re.match(r"(.*)\s(\S+)$", vessel_full)
        if match:
            data["ocean_vessel"] = match.group(1)
            data["voyage"] = match.group(2)
        else:
            data["ocean_vessel"] = vessel_full
            data["voyage"] = ""

        # ===== ETD =====
        m = re.search(r"ETD:\s*([A-Za-z]+\s\d{2},\s\d{4})", text)
        data["etd"] = m.group(1) if m else ""

        # ===== GOODS =====
        lines = text.split("\n")
        goods = []
        start = False

        for line in lines:
            if "Discription of Goods" in line or "Description of Goods" in line:
                start = True
                continue

            if start:
                if re.match(r"^1\s", line.strip()):
                    break
                if line.strip():
                    goods.append(line.strip())

        data["goods"] = " ".join(goods)

        # ===== TOTAL (CHUẨN FILE CỦA BẠN) =====
        packages = "0"
        gross = "0"
        cbm = "0"

        for i, line in enumerate(lines):
            if "TOTAL" in line:
                for j in range(i+1, min(i+6, len(lines))):
                    row = lines[j].strip()

                    if re.search(r"\d{1,3}(,\d{3})+", row):
                        nums = re.findall(r"[\d,]+\.\d+|[\d,]+", row)

                        if len(nums) >= 5:
                            packages = nums[0]
                            gross = nums[3]
                            cbm = nums[4]
                            break
                break

        data["packages"] = packages
        data["gross"] = gross
        data["cbm"] = cbm

        return data

    # ===== B/L NUMBER =====
    def generate_bl(etd):
        dt = datetime.strptime(etd, "%B %d, %Y")
        y = dt.year % 100
        m = dt.month

        res = supabase.table("bl_counter").select("*").eq("year", y).eq("month", m).execute()

        if res.data:
            current = res.data[0]["current_no"] + 2
            supabase.table("bl_counter").update({"current_no": current}).eq("year", y).eq("month", m).execute()
        else:
            current = 1
            supabase.table("bl_counter").insert({
                "year": y,
                "month": m,
                "current_no": current
            }).execute()

        return f"TRHY{y:02d}{m:02d}{current:03d}"

    # ===== FILL PDF =====
    def fill_pdf(data):
        template = PdfReader("template.pdf")

        for page in template.pages:
            if page.Annots:
                for annot in page.Annots:
                    key = annot.T[1:-1]

                    if key in data:
                        annot.V = str(data[key])
                        annot.AP = None

        output = "BL_output.pdf"
        PdfWriter().write(output, template)

        return output

    # ===== RUN =====
    if pdf_file:
        text = extract_text(pdf_file)
        data = parse(text)

        st.subheader("📋 Extracted Data")
        st.json(data)

        allow = False

        if excel_file:
            df = pd.read_excel(excel_file)

            container = data.get("container", "")

            if container == "":
                st.error("❌ Không đọc được container")
            else:
                match = df[df.apply(lambda r: container in str(r), axis=1)]

                if not match.empty:
                    st.success("✅ Container OK")

                    row_text = str(match.iloc[0]).lower()

                    if data["ocean_vessel"].lower() in row_text:
                        st.success("🚢 Vessel OK")
                    else:
                        st.error("❌ Vessel sai")

                    if data["pod"].lower() in row_text:
                        st.success("📍 POD OK")
                        allow = True
                    else:
                        st.error("❌ POD sai")

                else:
                    st.error("❌ Container không có")

        if allow:
            if st.button("📤 TẠO BILL (PDF)"):

                if data["etd"] == "":
                    st.error("❌ Thiếu ETD")
                    st.stop()

                data["bl_no"] = generate_bl(data["etd"])
                pdf_file = fill_pdf(data)

                try:
                    etd_date = datetime.strptime(data["etd"], "%B %d, %Y").date()

                    packages = int(data["packages"].replace(",", "")) if data["packages"] else 0
                    gross = float(data["gross"].replace(",", "")) if data["gross"] else 0
                    cbm = float(data["cbm"]) if data["cbm"] else 0

                    supabase.table("bill_of_lading").insert({
                        "bl_no": data["bl_no"],
                        "consignee": data["consignee"],
                        "container": data["container"],
                        "ocean_vessel": data["ocean_vessel"],
                        "voyage": data["voyage"],
                        "pod": data["pod"],
                        "etd": etd_date,
                        "packages": packages,
                        "gross": gross,
                        "cbm": cbm
                    }).execute()

                except Exception as e:
                    st.error(f"Lỗi DB: {e}")

                with open(pdf_file, "rb") as f:
                    st.download_button("⬇️ Download B/L PDF", f, file_name=data["bl_no"] + ".pdf")

        else:
            st.warning("⚠️ DATA chưa đúng → không cho export")

# =========================
# ===== DASHBOARD =====
# =========================
with tab2:

    st.title("📊 B/L DASHBOARD")

    res = supabase.table("bill_of_lading").select("*").execute()
    df = pd.DataFrame(res.data)

    if not df.empty:
        search = st.text_input("🔍 Search")

        if search:
            df = df[df.apply(lambda r: search.lower() in str(r).lower(), axis=1)]

        st.metric("📦 Total B/L", len(df))
        st.dataframe(df.sort_values(by="id", ascending=False))
    else:
        st.info("Chưa có dữ liệu")
