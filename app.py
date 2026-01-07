import streamlit as st
import pandas as pd
from fpdf import FPDF
import math
import io
import os
import re

# --- 1. CONFIGURATION & IMPORTS ---
st.set_page_config(page_title="SGM Valve Sizing Pro", layout="wide", page_icon="🛡️")

# --- 2. AUTHENTICATION ---
USERS = {
    "admin": {"password": "admin123", "role": "admin"},   # Full Access
    "user":  {"password": "user123",  "role": "viewer"}   # View Only
}

if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'user_role' not in st.session_state: st.session_state.user_role = None
if 'project_log' not in st.session_state: st.session_state.project_log = [] 
if 'last_results' not in st.session_state: st.session_state.last_results = None

def login():
    st.markdown("## 🔐 SGM Sizing Login")
    c1, c2 = st.columns([1, 2])
    with c1:
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.button("Log In"):
            if u in USERS and USERS[u]['password'] == p:
                st.session_state.authenticated = True
                st.session_state.user_role = USERS[u]['role']
                st.rerun()
            else:
                st.error("Invalid Username or Password")

if not st.session_state.authenticated:
    login()
    st.stop()

# --- 3. DATABASES & CONSTANTS ---
FLUID_DB = {
    "Air": {"mw": 28.96, "k": 1.40}, "Nitrogen": {"mw": 28.01, "k": 1.40},
    "Oxygen": {"mw": 32.00, "k": 1.40}, "Argon": {"mw": 39.95, "k": 1.67},
    "Natural Gas": {"mw": 19.00, "k": 1.27}, "CO2": {"mw": 44.01, "k": 1.30},
    "Ammonia": {"mw": 17.03, "k": 1.31}, "Chlorine": {"mw": 70.90, "k": 1.35},
    "LPG": {"mw": 51.00, "k": 1.13}, "Propane": {"mw": 44.10, "k": 1.13},
    "Ethane": {"mw": 30.07, "k": 1.19}, "Water": {"rho": 997.0, "visc": 1.0},
    "Oil (Generic)": {"rho": 850.0, "visc": 10.0}, "LDO": {"rho": 870.0, "visc": 3.5}
}

ORIFICE_DATA = {
    'B': {'area': 38.7, 'max_p': 420}, 'C': {'area': 57.0, 'max_p': 420},
    'D': {'area': 71.0, 'max_p': 420}, 'E': {'area': 126.5, 'max_p': 153},
    'F': {'area': 198.0, 'max_p': 51}, 'G': {'area': 324.5, 'max_p': 19.6},
    'H': {'area': 506.0, 'max_p': 19.6}, 'J': {'area': 830.0, 'max_p': 19.6},
    'K': {'area': 1186.0, 'max_p': 19.6}, 'L': {'area': 1841.0, 'max_p': 19.6},
    'M': {'area': 2323.0, 'max_p': 19.6}, 'N': {'area': 2800.0, 'max_p': 19.6},
    'P': {'area': 4116.0, 'max_p': 19.6}, 'Q': {'area': 7129.0, 'max_p': 19.6},
    'R': {'area': 10323.0, 'max_p': 19.6}, 'T': {'area': 16774.0, 'max_p': 19.6}
}

FLANGE_LIMITS = {
    "150#": 19.6, "300#": 51.1, "600#": 102.1, 
    "900#": 153.2, "1500#": 255.3, "2500#": 425.5
}

API_526_SIZES = {'D': ('1"', '2"'), 'E': ('1"', '2"'), 'F': ('1.5"', '2"'), 'G': ('1.5"', '2.5"'), 'H': ('1.5"', '3"'), 'J': ('2"', '3"'), 'K': ('3"', '4"'), 'L': ('3"', '4"'), 'M': ('4"', '6"'), 'N': ('4"', '6"'), 'P': ('4"', '6"'), 'Q': ('6"', '8"'), 'R': ('6"', '8"'), 'T': ('8"', '10"')}

def clean_text(text):
    if not isinstance(text, str): return str(text)
    replacements = {"°": "deg", "²": "2", "³": "3", "±": "+/-", "≥": ">=", "≤": "<="}
    for k, v in replacements.items(): text = text.replace(k, v)
    return text.encode('latin-1', 'ignore').decode('latin-1')

def get_spring_from_file(file_name, orifice, set_pressure):
    actual_files = {
        "spring_api.csv": ["Spring Table API 526.xlsx - Sheet1.csv", "spring_api.csv"],
        "spring_non_api.csv": ["Non- API 526 valve Spring table.xlsx - Sheet1.csv", "spring_non_api.csv"]
    }
    target_path = file_name
    if file_name in actual_files:
        for f in actual_files[file_name]:
            if os.path.exists(f): target_path = f; break
    
    if not os.path.exists(target_path): return f"Err: File missing", 0, 0
    try:
        df = pd.read_csv(target_path)
        df.columns = [str(c).strip().upper() for c in df.columns]
        if orifice not in df.columns: return f"Err: Orifice {orifice} not in CSV", 0, 0
        for index, row in df.iterrows():
            raw_val = str(row[orifice])
            match = re.search(r"(\d+\.?\d*)\s*[-–to]+\s*(\d+\.?\d*)", raw_val)
            if match:
                min_p, max_p = float(match.group(1)), float(match.group(2))
                if min_p <= set_pressure <= max_p: return str(row.iloc[0]), min_p, max_p
        return "Out of Spring Range", 0, 0
    except Exception as e: return f"CSV Error: {str(e)}", 0, 0

# --- 4. PDF ENGINE ---
class PDF(FPDF):
    def header(self):
        try: self.image('logo.png', 10, 8, 33) 
        except: pass 
        self.set_y(10); self.set_font('Arial', 'B', 16); self.cell(0, 10, 'Safety Valve Datasheet', 0, 1, 'C')
        self.set_font('Arial', 'B', 12); self.set_text_color(0, 51, 102); self.cell(0, 8, 'SGM Valves and System Pvt Ltd', 0, 1, 'C')
        self.set_text_color(0, 0, 0); self.ln(5); self.set_line_width(0.5); self.line(10, 32, 200, 32); self.ln(5)
    def footer(self):
        self.set_y(-15); self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()} - Generated by SGM Valves Sizing Tool', 0, 0, 'C')

def render_datasheet_page(pdf_obj, data_pack):
    proj, proc, fluid, mech, res, safety = data_pack['proj'], data_pack['proc'], data_pack['fluid'], data_pack['mech'], data_pack['res'], data_pack['safety']
    
    def print_section(title, data_dict):
        title = clean_text(title)
        pdf_obj.set_font("Arial", 'B', 11); pdf_obj.set_fill_color(230, 230, 230); pdf_obj.cell(0, 7, title, 0, 1, 'L', fill=True); pdf_obj.ln(1); pdf_obj.set_font("Arial", size=9)
        keys = list(data_dict.keys())
        for i in range(0, len(keys), 2):
            k1 = clean_text(keys[i]); v1 = clean_text(str(data_dict[keys[i]]))
            pdf_obj.cell(45, 6, f"{k1}:", 0, 0); pdf_obj.cell(50, 6, v1, 0, 0)
            if i + 1 < len(keys):
                k2 = clean_text(keys[i+1]); v2 = clean_text(str(data_dict[keys[i+1]]))
                pdf_obj.cell(45, 6, f"{k2}:", 0, 0); pdf_obj.cell(50, 6, v2, 0, 1)
            else: pdf_obj.ln(6)
        pdf_obj.ln(3)

    print_section("1. General Detail", proj)
    print_section("2. Process Conditions", proc)
    print_section("3. Fluid Properties & Coefficients", fluid)
    print_section("4. Mechanical Construction", mech)
    
    pdf_obj.ln(2); pdf_obj.set_fill_color(255, 255, 255); current_y = pdf_obj.get_y(); pdf_obj.rect(10, current_y, 190, 45, 'F'); pdf_obj.set_xy(10, current_y)
    pdf_obj.set_font("Arial", 'B', 11); pdf_obj.set_fill_color(230, 230, 230); pdf_obj.cell(190, 7, "5. Sizing & Selection Results", 0, 1, 'L', fill=True); pdf_obj.set_font("Arial", size=9); pdf_obj.ln(1)
    for k, v in res.items():
        k_clean, v_clean = clean_text(k), clean_text(str(v))
        pdf_obj.set_x(10); pdf_obj.cell(45, 6, f"{k_clean}:", 0, 0); pdf_obj.cell(140, 6, v_clean, 0, 1)
    
    pdf_obj.set_y(pdf_obj.get_y() + 5)
    print_section("6. Safety & Force Calculations", safety)

def generate_single_pdf(data_pack):
    pdf = PDF(); pdf.add_page()
    render_datasheet_page(pdf, data_pack)
    return pdf.output(dest='S').encode('latin-1', 'ignore')

def generate_combined_pdf(all_logs):
    pdf = PDF()
    for log_item in all_logs:
        pdf.add_page()
        render_datasheet_page(pdf, log_item['data'])
    return pdf.output(dest='S').encode('latin-1', 'ignore')

# ==========================================
# 5. APP UI (SIDEBAR)
# ==========================================
with st.sidebar:
    st.write(f"👤 **{st.session_state.user_role.upper()} MODE**")
    if st.button("Log Out"): st.session_state.authenticated = False; st.rerun()
    st.markdown("---")

st.sidebar.markdown("## ⚙️ Sizing Inputs")
calc_mode = st.sidebar.radio("Mode", ["Sizing (Find Orifice)", "Capacity (Find Flow)"], horizontal=True)

st.sidebar.header("1. General Detail")
customer = st.sidebar.text_input("Customer Name", "SGM Client")
tag_no = st.sidebar.text_input("Tag Number", "PSV-1001")
offer_no = st.sidebar.text_input("Offer No", "OFF-001") # KEY FILTER FIELD
enquiry_no = st.sidebar.text_input("Enquiry No", "ENQ-001")
valve_standard = st.sidebar.radio("Select Valve Standard", ["API 526 (Flanged)", "Non-API (TR-01)"])
def_model = "SV-526" if valve_standard == "API 526 (Flanged)" else "TR-01"
model_no = st.sidebar.text_input("Model No", def_model)

st.sidebar.markdown("---")
# 2. Fluid
st.sidebar.header("2. Fluid Selection")
service_type = st.sidebar.selectbox("Service Type", ["Gas/Vapor", "Liquid", "Steam", "Two-Phase"])
fluids = ["Custom"]
if service_type == "Gas/Vapor": fluids = ["Custom", "Air", "Nitrogen", "Oxygen", "Argon", "Natural Gas", "CO2", "Ammonia", "Chlorine", "LPG", "Propane", "Ethane"]
elif service_type == "Liquid": fluids = ["Custom", "Water", "Oil (Generic)", "LDO"]
selected_fluid = st.sidebar.selectbox("Select Fluid", fluids)

st.sidebar.markdown("---")
# 3. Process
st.sidebar.header("3. Process Conditions")
common_units = ["kg/hr", "lb/hr", "LPM", "LPH", "GPM"]
unit_options = common_units
if service_type == "Gas/Vapor": unit_options = ["Sm3/hr", "Nm3/hr", "SCFM", "SCFH"] + common_units

raw_W = 0.0; designated_orf = "D"
if calc_mode.startswith("Sizing"):
    raw_W = st.sidebar.number_input("Required Flow Rate", value=1000.0)
    unit_W = st.sidebar.selectbox("Flow Unit", unit_options, key="u_flow")
else:
    st.sidebar.info("Select Orifice for Capacity")
    designated_orf = st.sidebar.selectbox("Select Orifice", list(ORIFICE_DATA.keys()))
    unit_W = st.sidebar.selectbox("Output Unit", unit_options, key="u_flow_cap")

c1, c2 = st.sidebar.columns(2)
raw_P1 = c1.number_input("Set Pressure", value=15.0)
unit_P1 = c2.selectbox("Unit", ["barg", "psig", "kg/cm2g"], key="u_p1")
overpressure_opt = st.sidebar.selectbox("Overpressure", ["10% Accumulation", "16% Accumulation", "21% Fire Case"])
op_mult = 1.16 if "16%" in overpressure_opt else (1.21 if "21%" in overpressure_opt else 1.10)

raw_BP_const = st.sidebar.number_input("Constant Back Pressure", value=0.0)
raw_BP_var = st.sidebar.number_input("Variable Back Pressure", value=0.0)
total_bp = raw_BP_const + raw_BP_var
raw_T1 = st.sidebar.number_input("Temperature", value=45.0)
unit_T1 = st.sidebar.selectbox("Unit", ["°C", "°F"], key="u_t1")
vapor_pressure_barg = st.sidebar.number_input("Vapor Pressure (barg)", 0.02) if service_type == "Liquid" else 0.0

# Properties
st.sidebar.markdown("---")
u_Mw = 28.96; u_k = 1.4; u_rho = 997.0; u_visc = 1.0; u_Z = 0.95
if selected_fluid in FLUID_DB:
    p = FLUID_DB[selected_fluid]
    u_Mw = p.get("mw", 28.96); u_k = p.get("k", 1.4); u_rho = p.get("rho", 997.0); u_visc = p.get("visc", 1.0)

if service_type == "Gas/Vapor":
    u_Mw = st.sidebar.number_input("MW", u_Mw); u_k = st.sidebar.number_input("k", u_k); u_Z = st.sidebar.number_input("Z", u_Z)
elif service_type == "Liquid":
    u_rho = st.sidebar.number_input("Density", u_rho); u_visc = st.sidebar.number_input("Visc", u_visc)

with st.sidebar.expander("4. Coefficients"):
    Kd = st.number_input("Kd", 0.975 if service_type!="Liquid" else 0.65)
    Kb = st.number_input("Kb", 1.0); Kc = st.number_input("Kc", 1.0)

# 5. Mechanical
st.sidebar.markdown("---")
st.sidebar.header("5. Mechanical")
c_m1, c_m2 = st.sidebar.columns(2)
body_mat = c_m1.selectbox("Body", ["A216 Gr WCB", "SS316"]); nozzle_mat = c_m2.selectbox("Nozzle", ["SS316", "Monel"])
c_m3, c_m4 = st.sidebar.columns(2)
disc_mat = c_m3.selectbox("Disc", ["SS316", "SS304"]); spring_mat = c_m4.selectbox("Spring", ["Spring Steel", "SS316"])

st.sidebar.subheader("End Connections")
P_set_bar = raw_P1 / 14.5 if unit_P1 == "psig" else (raw_P1 * 0.98 if unit_P1 == "kg/cm2g" else raw_P1)
conn_str = ""; manual_dim_in = 0; manual_dim_out = 0

if valve_standard == "API 526 (Flanged)":
    c_conn1, c_conn2 = st.sidebar.columns(2)
    inlet_rating = c_conn1.selectbox("Inlet Rating", ["150#", "300#", "600#", "900#", "1500#", "2500#"], index=1)
    limit = FLANGE_LIMITS.get(inlet_rating, 20)
    if P_set_bar > limit: st.sidebar.error(f"🚨 Set P ({P_set_bar:.1f} bar) exceeds {inlet_rating} limit!")
    outlet_rating = c_conn2.selectbox("Outlet Rating", ["150#", "300#"], index=0)
    conn_str = f"{inlet_rating} x {outlet_rating} RF"
else: 
    conn_style = st.sidebar.radio("Connection Style", ["Threaded / Socket Weld", "Flanged"], horizontal=True)
    target_orf = designated_orf if calc_mode.startswith("Capacity") else st.sidebar.selectbox("Select Target Orifice (For Conn Check)", ["B","D","E","F","G"])
    max_p = ORIFICE_DATA[target_orf]['max_p']
    if P_set_bar > max_p: st.sidebar.error(f"⛔ Orifice {target_orf} Max Pressure is {max_p} bar!")

    if conn_style.startswith("Threaded"):
        sz_list = ["1/2\"", "3/4\"", "1\"", "1-1/2\"", "2\""]
        c1, c2, c3 = st.sidebar.columns(3)
        in_sz = c1.selectbox("Inlet", sz_list); out_sz = c2.selectbox("Outlet", sz_list); c_type = c3.selectbox("Type", ["NPT (M x F)", "NPT (F x F)", "BSP", "SW"])
        conn_str = f"{in_sz} x {out_sz} {c_type}"
    else:
        st.sidebar.caption(f"Filtering for Orifice: {target_orf}")
        valid_inlets = []
        if target_orf in ["B", "D"]: valid_inlets.extend(["1/2\"", "3/4\"", "1\""])
        if target_orf == "E": valid_inlets.extend(["3/4\"", "1\""])
        if target_orf in ["F", "G"]: valid_inlets.extend(["1\"", "1-1/2\""])
        in_sz = st.sidebar.selectbox("Inlet Size", sorted(list(set(valid_inlets))))
        valid_outlets = []
        if in_sz == "1/2\"": valid_outlets = ["1/2\"", "3/4\"", "1\""]
        elif in_sz == "3/4\"": valid_outlets = ["3/4\"", "1\""]
        elif in_sz == "1\"": valid_outlets = ["1\"", "1-1/2\""]
        elif in_sz == "1-1/2\"": valid_outlets = ["2\" (Std)"]
        out_sz = st.sidebar.selectbox("Outlet Size", valid_outlets)
        avail_in_ratings = [r for r, lim in FLANGE_LIMITS.items() if lim >= P_set_bar]
        if target_orf == "G" and P_set_bar < 20: avail_in_ratings = [r for r in avail_in_ratings if r in ["150#", "300#"]]
        c_r1, c_r2 = st.sidebar.columns(2)
        in_rate = c_r1.selectbox("Inlet Flange", avail_in_ratings)
        out_rate = c_r2.selectbox("Outlet Flange", ["150#", "300#", "600#"])
        conn_str = f"{in_sz} {in_rate} x {out_sz} {out_rate} RF"
    
    st.sidebar.markdown("**Manual Dimensions**")
    c_d1, c_d2 = st.sidebar.columns(2)
    manual_dim_in = c_d1.number_input("Inlet C-to-F", 0); manual_dim_out = c_d2.number_input("Outlet C-to-F", 0)

lever_type = st.sidebar.selectbox("Lever", ["None", "Packed", "Open"])
bellows_req = st.sidebar.checkbox("Bellows?", False)

# ==========================================
# 6. EXECUTION & DISPLAY
# ==========================================
st.title("🛡️ SGM Valves - Sizing Pro")
st.markdown("### 📊 Sizing Dashboard")

if st.button("🚀 Calculate & Generate Datasheet"):
    T_K = raw_T1 + 273.15 if unit_T1 == "°C" else (raw_T1 - 32)*5/9 + 273.15
    P1_abs = (P_set_bar * op_mult) + 1.013
    
    req_area = 0.0; sel_orf = ""; sel_area = 0.0; rated_cap = 0.0; form_str = ""
    
    if calc_mode.startswith("Sizing"):
        W_base = raw_W 
        if unit_W == "lb/hr": W_base = raw_W * 0.453
        elif unit_W == "Nm3/hr": W_base = (raw_W / 22.414) * u_Mw
        elif unit_W == "Sm3/hr": W_base = (raw_W / 23.64) * u_Mw
        elif unit_W == "SCFM": W_base = (raw_W * 1.699) * u_Mw
        elif unit_W == "SCFH": W_base = (raw_W * 1.699 / 60) * u_Mw
        elif unit_W == "LPM": W_base = raw_W * 0.06 * u_rho
        elif unit_W == "LPH": W_base = raw_W * 0.001 * u_rho
        elif unit_W == "GPM": W_base = raw_W * 0.227 * u_rho
        
        if service_type == "Gas/Vapor":
            C = 520 * math.sqrt(u_k * ((2/(u_k+1))**((u_k+1)/(u_k-1)))) 
            term = math.sqrt((T_K * u_Z) / u_Mw)
            req_area = (W_base * term * 13160) / (C * Kd * (P1_abs*100) * Kb * Kc)
            form_str = "A = (W * sqrt(T*Z*M)) / (C * Kd * P1 * Kb * Kc)"
        elif service_type == "Liquid":
            dP = (P_set_bar * op_mult) - total_bp
            if dP <= 0: st.error("Back Pres Error"); st.stop()
            Q_gpm = (W_base / u_rho) * 4.403
            req_area = (Q_gpm * math.sqrt(u_rho/1000)) / (38 * Kd * math.sqrt(dP*14.5)) * 645.16
            form_str = "A = Q / (Kd * sqrt(dP))"
            
        chk_orf = ORIFICE_DATA if valve_standard.startswith("Non") else {k:v for k,v in ORIFICE_DATA.items() if k in API_526_SIZES}
        for l, d in chk_orf.items():
            if d['area'] >= req_area and P_set_bar <= d['max_p']:
                sel_orf = l; sel_area = d['area']; break
        if not sel_orf: st.error("No Orifice Found"); st.stop()
        
    else: # Capacity Mode
        sel_orf = designated_orf; sel_area = ORIFICE_DATA[sel_orf]['area']; form_str = "Rated Capacity"
        if P_set_bar > ORIFICE_DATA[sel_orf]['max_p']: st.warning("Pressure Exceeded!")

    # Reverse Calc
    if service_type == "Gas/Vapor":
        C = 520 * math.sqrt(u_k * ((2/(u_k+1))**((u_k+1)/(u_k-1)))) 
        term = math.sqrt((T_K * u_Z) / u_Mw)
        W_rated = (sel_area * C * Kd * (P1_abs*100) * Kb * Kc) / (13160 * term)
    else:
        dP = (P_set_bar * op_mult) - total_bp
        W_rated = 0
        if dP > 0:
            Q_gpm = ((sel_area/645.16) * 38 * Kd * math.sqrt(dP*14.5)) / math.sqrt(u_rho/1000)
            W_rated = (Q_gpm / 4.403) * u_rho

    disp_cap = W_rated
    if unit_W == "lb/hr": disp_cap = W_rated / 0.453
    elif unit_W == "Nm3/hr": disp_cap = (W_rated / u_Mw) * 22.414
    elif unit_W == "Sm3/hr": disp_cap = (W_rated / u_Mw) * 23.64
    elif unit_W == "SCFM": disp_cap = (W_rated / u_Mw) / 1.699
    elif unit_W == "SCFH": disp_cap = (W_rated / u_Mw) / (1.699/60)
    elif unit_W == "LPM": disp_cap = W_rated / (0.06 * u_rho)
    elif unit_W == "LPH": disp_cap = W_rated / (0.001 * u_rho)
    elif unit_W == "GPM": disp_cap = W_rated / (0.227 * u_rho)

    fname = "spring_api.csv" if "API" in valve_standard else "spring_non_api.csv"
    res_c, res_min, res_max = get_spring_from_file(fname, sel_orf, P_set_bar)
    spring_txt = f"{res_c} ({res_min}-{res_max} bar)" if not str(res_c).startswith("Err") else str(res_c)
    
    force_spr = (P_set_bar * 0.1) * sel_area
    W_kgs = W_rated / 3600.0
    force_react = 0; noise = "Safe"
    if service_type == "Gas/Vapor":
        force_react = 1.29 * W_kgs * math.sqrt((u_k*T_K)/((u_k+1)*u_Mw))
        try: noise = f"{12 + 17*math.log10(W_kgs) + 50*math.log10(P_set_bar):.1f} dBA"
        except: pass
    else:
        force_react = (W_kgs**2) / (u_rho * (sel_area*6/1e6))
        if total_bp < vapor_pressure_barg: noise = "!! FLASHING !!"
        elif (P_set_bar - total_bp) > 0.6*(P_set_bar - vapor_pressure_barg): noise = "CAVITATION"

    req_str = f"{raw_W} {unit_W}" if calc_mode.startswith("Sizing") else "N/A"
    proj = {"Customer": customer, "Tag": tag_no, "Offer": offer_no, "Enquiry": enquiry_no, "Model No": model_no}
    proc = {"Service": service_type, "Fluid": selected_fluid, "Set P": f"{raw_P1} {unit_P1}", "Flow": req_str, "Overpressure": overpressure_opt}
    mech = {"Standard": valve_standard, "Size": conn_str, "Body": body_mat, "Trim": nozzle_mat, "Orifice": sel_orf}
    res = {"Req Area": f"{req_area:.2f} mm2", "Sel Area": f"{sel_area} mm2", "RATED CAP": f"{disp_cap:.2f} {unit_W}", "Formula": form_str}
    safe = {"Spring": spring_txt, "Spring Load": f"{force_spr:.1f} N", "React Force": f"{force_react:.1f} N", "Noise": noise}
    fluid_d = {"MW": u_Mw, "k": u_k, "SG": f"{u_rho/1000:.3f}", "Kd": Kd}
    
    # Store full Data for PDF Generation
    full_data = {'proj': proj, 'proc': proc, 'fluid': fluid_d, 'mech': mech, 'res': res, 'safety': safe}
    pdf_b = generate_single_pdf(full_data)
    
    st.session_state.last_results = {"cap": disp_cap, "unit": unit_W, "orf": sel_orf, "spr": spring_txt}
    # Log Entry now includes 'Offer' for filtering
    st.session_state.project_log.append({"Tag": tag_no, "Offer": offer_no, "Orifice": sel_orf, "PDF": pdf_b, "data": full_data})

# --- RESULTS & HISTORY ---
if st.session_state.last_results:
    r = st.session_state.last_results
    st.success(f"Rated Capacity: {r['cap']:.2f} {r['unit']}")
    st.metric("Orifice / Spring", f"{r['orf']} / {r['spr']}")
    if st.session_state.user_role == 'admin':
        st.download_button("📥 Datasheet", st.session_state.project_log[-1]['PDF'], f"{tag_no}.pdf", "application/pdf")

st.markdown("---")
st.markdown("### 🗃️ Project History")

# Filter Log by Current Offer No
current_offer_filter = offer_no.strip()
filtered_history = [item for item in st.session_state.project_log if item.get('Offer') == current_offer_filter]

if filtered_history:
    disp_log = [{k: v for k, v in item.items() if k not in ['PDF', 'data']} for item in filtered_history]
    st.table(pd.DataFrame(disp_log))
    
    if st.session_state.user_role == 'admin':
        if st.button("📦 Download Project Report (Single PDF)"):
            combined_pdf_bytes = generate_combined_pdf(filtered_history)
            st.download_button("⬇️ Click to Download Combined Report", combined_pdf_bytes, f"Project_{current_offer_filter}.pdf", "application/pdf")
else:
    st.info(f"No sizing history found for Offer No: {current_offer_filter}")
