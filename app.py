import streamlit as st
import numpy as np
import pandas as pd
from fpdf import FPDF
import math
import zipfile
import io
import csv
import os
from datetime import datetime

# --- 1. SAFE IMPORT ---
try:
    import CoolProp.CoolProp as CP
    COOLPROP_AVAILABLE = True
except ImportError:
    COOLPROP_AVAILABLE = False

# ==========================================
# 2. AUTHENTICATION & CONFIGURATION
# ==========================================
st.set_page_config(page_title="SGM Valve Sizing", layout="wide", page_icon="🛡️")

# --- USER DATABASE ---
USERS = {
    "admin": {"password": "admin123", "role": "admin", "can_download": True},
    "user":  {"password": "user123",  "role": "user",  "can_download": False},
    "guest": {"password": "guest",    "role": "user",  "can_download": False}
}

if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if 'username' not in st.session_state: st.session_state.username = None
if 'project_log' not in st.session_state: st.session_state.project_log = []

def login_screen():
    st.markdown("## 🔐 SGM Sizing Login")
    c1, c2 = st.columns([1, 2])
    with c1:
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if username in USERS and USERS[username]['password'] == password:
                st.session_state.authenticated = True; st.session_state.username = username; st.rerun()
            else: st.error("Invalid Username or Password")

def logout():
    st.session_state.authenticated = False; st.session_state.username = None; st.rerun()

def log_activity(user, tag, service, p1, p2):
    file_name = "activity_log.csv"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_exists = os.path.isfile(file_name)
    with open(file_name, mode='a', newline='') as f:
        writer = csv.writer(f)
        if not file_exists: writer.writerow(["Timestamp", "User", "Tag No", "Service", "Set Pressure", "Total Back Pressure"])
        writer.writerow([timestamp, user, tag, service, p1, p2])

if not st.session_state.authenticated: login_screen(); st.stop()

current_user = st.session_state.username
can_download = USERS[current_user]['can_download']

# --- SIDEBAR: User Info & Logout ---
st.sidebar.info(f"👤 Logged in as: **{current_user}**")
if st.sidebar.button("Log Out"): logout()
st.sidebar.markdown("---")

# --- DATA ---
flange_limits_barg = {"150#": 19.6, "300#": 51.1, "600#": 102.1, "900#": 153.2, "1500#": 255.3, "2500#": 425.5}
api_526_sizes = {'D': ('1"', '2"'), 'E': ('1"', '2"'), 'F': ('1.5"', '2"'), 'G': ('1.5"', '2.5"'), 'H': ('1.5"', '3"'), 'J': ('2"', '3"'), 'K': ('3"', '4"'), 'L': ('3"', '4"'), 'M': ('4"', '6"'), 'N': ('4"', '6"'), 'P': ('4"', '6"'), 'Q': ('6"', '8"'), 'R': ('6"', '8"'), 'T': ('8"', '10"')}

# FULL ORIFICE LIST (Includes B & C for Non-API)
all_orifices = {'B': 28, 'C': 57, 'D': 71, 'E': 126, 'F': 198, 'G': 325, 'H': 506, 'J': 830, 'K': 1186, 'L': 1841, 'M': 2323, 'N': 2800, 'P': 4116, 'Q': 7129, 'R': 10323, 'T': 16774}

# --- API 526 CENTER-TO-FACE DIMENSIONS (mm) ---
api_526_dims = {
    ('D', '150#', '150#'): (105, 114), ('D', '300#', '150#'): (105, 114), ('D', '600#', '150#'): (105, 114), ('D', '900#', '300#'): (140, 165), ('D', '1500#', '300#'): (140, 165),
    ('E', '150#', '150#'): (105, 121), ('E', '300#', '150#'): (105, 121), ('E', '600#', '150#'): (105, 121), ('E', '900#', '300#'): (140, 165), ('E', '1500#', '300#'): (140, 165),
    ('F', '150#', '150#'): (124, 121), ('F', '300#', '150#'): (124, 121), ('F', '600#', '150#'): (124, 121),
    ('G', '150#', '150#'): (124, 121), ('G', '300#', '150#'): (124, 121), ('G', '600#', '150#'): (124, 121),
    ('H', '150#', '150#'): (130, 124), ('H', '300#', '150#'): (130, 124), ('H', '600#', '150#'): (130, 124),
    ('J', '150#', '150#'): (137, 124), ('J', '300#', '150#'): (137, 124), ('J', '600#', '150#'): (137, 124),
    ('K', '150#', '150#'): (156, 162), ('K', '300#', '150#'): (156, 162), ('K', '600#', '150#'): (156, 162),
    ('L', '150#', '150#'): (156, 165), ('L', '300#', '150#'): (156, 165), ('L', '600#', '150#'): (156, 165),
    ('M', '150#', '150#'): (181, 184), ('M', '300#', '150#'): (181, 184), ('M', '600#', '150#'): (181, 184),
    ('N', '150#', '150#'): (197, 197), ('N', '300#', '150#'): (197, 197), ('N', '600#', '150#'): (197, 197),
    ('P', '150#', '150#'): (181, 229), ('P', '300#', '150#'): (181, 229), ('P', '600#', '150#'): (181, 229),
    ('Q', '150#', '150#'): (240, 241), ('Q', '300#', '150#'): (240, 241), ('Q', '600#', '150#'): (240, 241),
    ('R', '150#', '150#'): (240, 267), ('R', '300#', '150#'): (240, 267), ('R', '600#', '150#'): (240, 267),
    ('T', '150#', '150#'): (276, 279), ('T', '300#', '150#'): (276, 279),
}

def get_api_dimensions(letter, in_rate, out_rate):
    return api_526_dims.get((letter, in_rate, out_rate), None)

def calculate_eta_c(omega):
    if omega <= 0: return 1.0
    eta = 0.6 
    for _ in range(50):
        try:
            f = eta**2 + (omega**2 - 1)*eta**(2*omega) + 2*(omega**2)*math.log(eta) - 2*omega - 2*(omega**2)
            df = 2*eta + (omega**2 - 1)*(2*omega)*eta**(2*omega - 1) + 2*(omega**2)/eta
            if df == 0: break
            eta_new = eta - f/df
            if abs(eta_new - eta) < 0.00001: return eta_new
            eta = eta_new
        except: return 0.6
    return eta

# --- PDF GENERATOR ---
def create_datasheet(project_data, process_data, valve_data, mech_data, results_data):
    class PDF(FPDF):
        def header(self):
            try: self.image('watermark.png', x=45, y=80, w=120) 
            except: pass 
            try: self.image('logo.png', 10, 8, 33) 
            except: pass 
            self.set_y(10); self.set_font('Arial', 'B', 16); self.cell(0, 10, 'Safety Valve Datasheet', 0, 1, 'C')
            self.set_font('Arial', 'B', 12); self.set_text_color(0, 51, 102); self.cell(0, 8, 'SGM Valves and System Pvt Ltd', 0, 1, 'C')
            self.set_text_color(0, 0, 0); self.ln(5); self.set_line_width(0.5); self.line(10, 32, 200, 32); self.ln(5)
        def footer(self):
            self.set_y(-15); self.set_font('Arial', 'I', 8)
            self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'L'); self.cell(0, 10, 'Generated by SGM Valves Sizing Tool', 0, 0, 'R')

    pdf = PDF(); pdf.add_page()
    def print_section(title, data_dict):
        pdf.set_font("Arial", 'B', 11); pdf.set_fill_color(230, 230, 230); pdf.cell(0, 7, title, 0, 1, 'L', fill=True); pdf.ln(1); pdf.set_font("Arial", size=9)
        keys = list(data_dict.keys())
        for i in range(0, len(keys), 2):
            k1 = keys[i]; v1 = str(data_dict[k1])
            pdf.cell(45, 6, f"{k1}:", 0, 0); pdf.cell(50, 6, v1, 0, 0)
            if i + 1 < len(keys):
                k2 = keys[i+1]; v2 = str(data_dict[k2])
                pdf.cell(45, 6, f"{k2}:", 0, 0); pdf.cell(50, 6, v2, 0, 1)
            else: pdf.ln(6)
        pdf.ln(3)

    print_section("1. General Detail", project_data)
    print_section("2. Process Conditions", process_data)
    print_section("3. Fluid Properties & Coefficients", valve_data)
    print_section("4. Mechanical Construction", mech_data)
    
    pdf.ln(2); pdf.set_fill_color(255, 255, 255); current_y = pdf.get_y(); pdf.rect(10, current_y, 190, 45, 'F'); pdf.set_xy(10, current_y)
    pdf.set_font("Arial", 'B', 11); pdf.set_fill_color(230, 230, 230); pdf.cell(190, 7, "5. Sizing & Selection Results", 0, 1, 'L', fill=True); pdf.set_font("Arial", size=9); pdf.ln(1)
    keys = list(results_data.keys())
    for k in keys:
        v = str(results_data[k]); pdf.set_x(10); pdf.cell(45, 6, f"{k}:", 0, 0)
        if k == "Formula Used": pdf.set_font("Arial", 'I', 8); pdf.multi_cell(140, 6, v, 0, 'L')
        else: pdf.cell(140, 6, v, 0, 1)
    return pdf.output(dest='S').encode('latin-1')

def get_fluid_properties(fluid_name, T_kelvin, P_kpaa, quality_x=None, service="Gas/Vapor"):
    if not COOLPROP_AVAILABLE: return {"error": "No Lib"}
    try:
        P_pa = P_kpaa * 1000
        if service == "Two-Phase" and quality_x is not None:
            rho_0 = CP.PropsSI('D', 'P', P_pa, 'Q', quality_x, fluid_name); v_0 = 1 / rho_0; s_0 = CP.PropsSI('S', 'P', P_pa, 'Q', quality_x, fluid_name)
            P9_pa = 0.9 * P_pa; rho_9 = CP.PropsSI('D', 'P', P9_pa, 'S', s_0, fluid_name); v_9 = 1 / rho_9
            omega = 9 * ((v_9 / v_0) - 1); return {"rho": rho_0, "omega": omega, "error": None}
        else:
            rho = CP.PropsSI('D', 'T', T_kelvin, 'P', P_pa, fluid_name); Z = CP.PropsSI('Z', 'T', T_kelvin, 'P', P_pa, fluid_name); mw = CP.PropsSI('M', 'T', T_kelvin, 'P', P_pa, fluid_name) * 1000
            try: cp = CP.PropsSI('Cpmass', 'T', T_kelvin, 'P', P_pa, fluid_name); cv = CP.PropsSI('Cvmass', 'T', T_kelvin, 'P', P_pa, fluid_name); k = cp/cv
            except: k = 1.01 
            try: visc = CP.PropsSI('V', 'T', T_kelvin, 'P', P_pa, fluid_name) * 1000
            except: visc = 0.0
            return {"rho": rho, "Z": Z, "k": k, "Mw": mw, "visc": visc, "error": None}
    except Exception as e: return {"error": str(e)}

# ==========================================
# 4. APP LAYOUT
# ==========================================
st.title("🛡️ SGM Valves - Sizing Pro")

# --- CALCULATION MODE SWITCH ---
st.sidebar.markdown("### ⚙️ Calculation Mode")
calc_mode = st.sidebar.radio("Method", ["Sizing (Find Orifice)", "Capacity (Find Flow)"], label_visibility="collapsed")
st.sidebar.markdown("---")

st.sidebar.header("1. General Detail")
customer = st.sidebar.text_input("Customer Name", "SGM Client")
tag_no = st.sidebar.text_input("Tag Number", "PSV-1001")
enquiry_no = st.sidebar.text_input("Enquiry No", "ENQ-001")
offer_no = st.sidebar.text_input("Offer No", "OFF-001")
desc = st.sidebar.text_input("Description", "Separator Relief")

st.sidebar.markdown("---")
st.sidebar.header("2. Fluid Selection")
service_type = st.sidebar.selectbox("Service Type", ["Gas/Vapor", "Liquid", "Steam", "Two-Phase"])
fluids = ["Custom (Manual Input)", "Water", "Air", "Nitrogen", "Oxygen", "CO2", "Methane", "Propane", "Ammonia"]
if not COOLPROP_AVAILABLE: fluids = ["Custom (Manual Input)"]
idx_def = 0
if service_type == "Steam" and "Water" in fluids: idx_def = fluids.index("Water")
selected_fluid = st.sidebar.selectbox("Select Fluid", fluids, index=idx_def)

st.sidebar.markdown("---")
st.sidebar.header("3. Process Conditions")
flow_units = ["kg/hr", "lb/hr", "Nm3/hr", "Sm3/hr", "SCFM", "SCFH", "LPM", "m3/hr", "LPH"]
def input_w_unit(lbl, def_val, units, k):
    c1, c2 = st.sidebar.columns([2,1])
    return c1.number_input(lbl, value=def_val, key=k+"_v"), c2.selectbox("U", units, key=k+"_u")

# --- CONDITIONAL INPUT: FLOW vs ORIFICE ---
raw_W, unit_W = 0.0, "kg/hr"
sel_orifice_cap = "D"

if calc_mode == "Sizing (Find Orifice)":
    raw_W, unit_W = input_w_unit("Required Flow Rate", 1000.0, flow_units, "w")
else:
    # Capacity Mode
    st.sidebar.markdown("**Select Orifice to find Capacity:**")
    sel_orifice_cap = st.sidebar.selectbox("Designated Orifice", list(all_orifices.keys()))
    unit_W = st.sidebar.selectbox("Output Flow Unit", flow_units)

press_units = ["barg", "psig", "kPag", "kg/cm2g"]
raw_P1, unit_P1 = input_w_unit("Set Pressure", 10.0, press_units, "p1")

# --- Overpressure Selection ---
overpressure_pct = st.sidebar.selectbox("Allowable Overpressure", ["10%", "21%"])
op_mult = 1.10 if overpressure_pct == "10%" else 1.21

raw_BP_const, unit_BP_const = input_w_unit("Constant Back Pressure", 0.0, press_units, "p2_c")
raw_BP_var, unit_BP_var = input_w_unit("Variable Back Pressure", 0.0, press_units, "p2_v")
raw_T1, unit_T1 = input_w_unit("Temperature", 150.0, ["°C", "°F", "K"], "t1")

# --- PRESSURE CALCS ---
atm = 101.325
def get_kpa_gauge(raw, unit):
    if unit == "barg": return raw * 100
    if unit == "psig": return raw * 6.89476
    if unit == "kg/cm2g": return raw * 98.0665
    if unit == "kPag": return raw
    return raw
def to_kpa_abs_from_gauge(gauge_kpa): return gauge_kpa + atm

P1_gauge_kpa = get_kpa_gauge(raw_P1, unit_P1)
P1_abs = to_kpa_abs_from_gauge(P1_gauge_kpa)
BP_const_kpa = get_kpa_gauge(raw_BP_const, unit_BP_const)
BP_var_kpa = get_kpa_gauge(raw_BP_var, unit_BP_var)
P2_gauge_total_kpa = BP_const_kpa + BP_var_kpa
P2_abs = to_kpa_abs_from_gauge(P2_gauge_total_kpa)

p1_bar_equiv = P1_gauge_kpa / 100
p2_bar_total_equiv = P2_gauge_total_kpa / 100
back_pressure_ratio = 0.0
if p1_bar_equiv > 0: back_pressure_ratio = (p2_bar_total_equiv / p1_bar_equiv) * 100
bellows_recommended = False
if back_pressure_ratio > 10:
    bellows_recommended = True
    st.sidebar.warning(f"⚠️ Total Back Pressure is {back_pressure_ratio:.1f}% (>10%). Bellows Recommended!")

input_quality = 0.0
omega_manual = 1.0
rho_inlet_manual = 1000.0
if service_type == "Two-Phase":
    st.sidebar.markdown("**Two-Phase Properties**")
    input_quality = st.sidebar.number_input("Vapor Mass Fraction (Quality x)", value=0.1, min_value=0.0, max_value=1.0)
    if selected_fluid == "Custom (Manual Input)":
        omega_manual = st.sidebar.number_input("Omega Parameter (w)", value=1.0)
        rho_inlet_manual = st.sidebar.number_input("Inlet Density (kg/m3)", value=500.0)

Ksh_manual = 1.0
if service_type == "Steam" and selected_fluid == "Custom (Manual Input)":
    st.sidebar.markdown("**Steam Correction**")
    Ksh_manual = st.sidebar.number_input("Superheat Correction Factor (Ksh)", value=1.0)

with st.sidebar.expander("4. Coefficients (Kd, Kb, Kc)"):
    def_kd = 0.975 if service_type in ["Gas/Vapor", "Steam", "Two-Phase"] else 0.65
    Kd = st.number_input("Kd (Discharge)", value=def_kd)
    Kb = st.number_input("Kb (Back Pres Factor)", value=1.0)
    Kc = st.number_input("Kc (Rupture Disc)", value=1.0)
    Kv = st.number_input("Kv (Viscosity)", value=1.0)

st.sidebar.markdown("---")
st.sidebar.header("5. Mechanical Construction")
valve_standard = st.sidebar.radio("Select Valve Standard", ["API 526 (Flanged)", "Non-API / Compact (Threaded)"])
st.sidebar.markdown("---")

moc_body_list = ["A216 Gr WCB", "A351 Gr CF8", "A351 Gr CF8M", "A351 Gr CF3", "A351 Gr CF3M", "Other"]
moc_trim_list = ["SS316", "SS304", "SS316L", "SS304L", "A351 Gr CF8", "A351 Gr CF8M", "Hastelloy C", "Monel", "Alloy 20", "Inconel", "Other"]
moc_spring_list = ["Spring Steel", "Chrome Steel", "SS316", "High Temp Alloy Steel", "Inconel", "Inconel X750", "Other"]

c_m1, c_m2 = st.sidebar.columns(2)
sel_body = c_m1.selectbox("Body Material", moc_body_list); body_mat = st.sidebar.text_input("Specify Body", "") if sel_body == "Other" else sel_body
sel_nozzle = c_m2.selectbox("Nozzle Material", moc_trim_list); nozzle_mat = st.sidebar.text_input("Specify Nozzle", "") if sel_nozzle == "Other" else sel_nozzle
c_m3, c_m4 = st.sidebar.columns(2)
sel_disc = c_m3.selectbox("Disc Material", moc_trim_list); disc_mat = st.sidebar.text_input("Specify Disc", "") if sel_disc == "Other" else sel_disc
sel_spring = c_m4.selectbox("Spring Material", moc_spring_list); spring_mat = st.sidebar.text_input("Specify Spring", "") if sel_spring == "Other" else sel_spring

inlet_str = "N/A"; outlet_str = "N/A"; sel_inlet_sz = ""; sel_outlet_sz = ""; inlet_rating = ""; outlet_rating = ""
st.sidebar.subheader("End Connections")
if valve_standard == "API 526 (Flanged)":
    c_conn1, c_conn2 = st.sidebar.columns(2)
    inlet_rating = c_conn1.selectbox("Inlet Rating", ["150#", "300#", "600#", "900#", "1500#", "2500#"], index=1)
    if inlet_rating in flange_limits_barg:
        limit = flange_limits_barg[inlet_rating]
        if p1_bar_equiv > limit: st.sidebar.error(f"🚨 Set Pressure ({p1_bar_equiv:.1f} bar) exceeds {inlet_rating} rating limit (~{limit} bar)!")
    outlet_rating = c_conn2.selectbox("Outlet Rating", ["150#", "300#", "150#"], index=0)
    conn_type = st.sidebar.selectbox("Connection Type", ["RF Flange", "RTJ Flange"])
    inlet_str = f"{inlet_rating} {conn_type}"; outlet_str = f"{outlet_rating} {conn_type}"
else:
    c_sz1, c_sz2 = st.sidebar.columns(2)
    sel_inlet_sz = c_sz1.selectbox("Inlet Size", options=["1/2\"", "3/4\"", "1\"", "1 1/2\"", "2\""], index=0)
    sel_outlet_sz = c_sz2.selectbox("Outlet Size", options=["1/2\"", "3/4\"", "1\"", "1 1/2\"", "2\""], index=1)
    conn_type = st.sidebar.selectbox("Connection Type", ["NPT (Male x Female)", "NPT (Female x Female)", "BSP", "Socket Weld"])
    inlet_str = f"{sel_inlet_sz} {conn_type.split(' ')[0]}"; outlet_str = f"{sel_outlet_sz} {conn_type.split(' ')[0]}"

st.sidebar.subheader("Dimensions (Non-API Manual)")
c_dim1, c_dim2 = st.sidebar.columns(2)
c_face_inlet_manual = c_dim1.number_input("C-to-Face Inlet (mm)", value=0)
c_face_outlet_manual = c_dim2.number_input("C-to-Face Outlet (mm)", value=0)
lever_type = st.sidebar.selectbox("Lever Type", ["None", "Packed Lever", "Plain Lever", "Open Lever"])
bellows = st.sidebar.checkbox("Bellows Required?", value=False)

T_K = (raw_T1 + 273.15) if unit_T1 == "°C" else ((raw_T1 - 32) * 5/9 + 273.15) if unit_T1 == "°F" else raw_T1
u_Mw, u_k, u_Z, u_SG, u_visc, u_omega, u_rho = 44.0, 1.3, 0.95, 1.0, 1.0, 1.0, 10.0

if selected_fluid != "Custom (Manual Input)":
    if service_type == "Two-Phase":
        p = get_fluid_properties(selected_fluid, T_K, P1_abs, quality_x=input_quality, service="Two-Phase")
        if not p['error']: u_omega, u_rho = p['omega'], p['rho']
        else: st.sidebar.error("Two-Phase Error: " + p['error'])
    else:
        p = get_fluid_properties(selected_fluid, T_K, P1_abs, service=service_type)
        if not p['error']: u_Mw, u_k, u_Z, u_SG, u_visc, u_rho = p['Mw'], p['k'], p['Z'], p['rho']/1000, p['visc'], p['rho']
        else: st.sidebar.error("Prop Error")

if selected_fluid == "Custom (Manual Input)":
    st.sidebar.warning("Using Manual Properties")
    if service_type == "Two-Phase": pass
    else:
        u_Mw = st.sidebar.number_input("MW", value=44.0)
        u_k = st.sidebar.number_input("k", value=1.3, min_value=1.01)
        u_Z = st.sidebar.number_input("Z", value=0.95)
        u_SG = st.sidebar.number_input("SG", value=1.0)

W_base = 0.0
# --- UPDATED: Conversion Logic for Sizing Mode ---
if calc_mode == "Sizing (Find Orifice)":
    if unit_W == "kg/hr": W_base = raw_W
    elif unit_W == "lb/hr": W_base = raw_W * 0.453592
    elif unit_W == "Nm3/hr": W_base = (raw_W / 22.414) * u_Mw if u_Mw > 0 else 0
    elif unit_W == "Sm3/hr": W_base = (raw_W / 23.64) * u_Mw if u_Mw > 0 else 0 
    elif unit_W == "SCFM": 
        scfh = raw_W * 60
        w_lb_hr = (scfh / 379.5) * u_Mw if u_Mw > 0 else 0
        W_base = w_lb_hr * 0.453592
    elif unit_W == "SCFH":
        w_lb_hr = (raw_W / 379.5) * u_Mw if u_Mw > 0 else 0
        W_base = w_lb_hr * 0.453592
    elif unit_W == "LPM": W_base = (raw_W * 0.06 / 22.414) * u_Mw if u_Mw > 0 else 0
    elif unit_W == "m3/hr": W_base = raw_W * 1000 * u_SG
    elif unit_W == "LPH": W_base = raw_W * u_SG

# ==========================================
# 6. EXECUTION
# ==========================================
st.markdown("### 📊 Sizing Dashboard")

if st.button("🚀 Calculate & Generate Datasheet"):
    log_activity(current_user, tag_no, service_type, f"{raw_P1} {unit_P1}", f"{raw_BP_const+raw_BP_var} {unit_BP_const}")
    try:
        if bellows_recommended and not bellows: st.warning("⚠️ WARNING: Back Pressure > 10% but 'Bellows Required' is NOT checked.")
        
        P1_sizing = (P1_abs - atm) * op_mult + atm 
        dP = P1_sizing - P2_abs
        
        # --- CALCULATION LOGIC ---
        A_final = 0.0
        W_capacity = 0.0
        sel_orf = ""
        sel_letter = ""
        calc_note = ""
        formula_used = ""

        # --- 1. DETERMINE AREA OR CAPACITY ---
        if calc_mode == "Sizing (Find Orifice)":
            # FORWARD: Find Area
            if service_type in ["Gas/Vapor", "Steam"]:
                k_term = (u_k+1)/(u_k-1); C = 520 * np.sqrt(u_k * ((2/(u_k+1))**k_term))
                Kn = 1.0; Ksh = 1.0
                if service_type == "Steam":
                    if P1_sizing > 10443: Kn = (0.276 * (P1_sizing/1000) - 1000) / (0.33 * (P1_sizing/1000) - 1061); calc_note = "Napier Correction (Kn) applied."
                    if selected_fluid == "Custom (Manual Input)": Ksh = Ksh_manual
                num = 13160 * W_base * np.sqrt((T_K * u_Z) / u_Mw); den = C * Kd * P1_sizing * Kb * Kc * Kn * Ksh
                A_final = num / den; formula_used = "A = (W * sqrt(T*Z/M)) / (C * Kd * P1 * Kb * Kc)"
            
            elif service_type == "Liquid":
                Q_lpm = (W_base / u_SG) / 60
                if dP <= 0: st.error("Back Pres > Set Pres!"); st.stop()
                A_final = (11.78 * Q_lpm / (Kd * Kb * Kc * Kv)) * np.sqrt(u_SG / dP)
                formula_used = "A = (Q_gpm/38) / (Kd * Kw * Kc * Kv) * sqrt(G / (P1-P2))"
            
            elif service_type == "Two-Phase":
                eta_c = calculate_eta_c(u_omega); P_cf = eta_c * P1_sizing; is_critical = P2_abs < P_cf
                calc_note = f"Flow is {'Critical' if is_critical else 'Subcritical'} (eta_c={eta_c:.3f})"
                v_0 = 1.0 / u_rho; P0 = P1_sizing * 1000
                G_si = eta_c * math.sqrt((P0/v_0)/u_omega) if is_critical else eta_c * math.sqrt((P0/v_0)/u_omega) # Simplified
                W_kg_s = W_base / 3600; A_m2 = W_kg_s / (G_si * 0.9 * Kd * Kb * Kc); A_final = A_m2 * 1e6
                formula_used = "A = W / (G_flux * Kd * Kb * Kc * 0.9)"

            # Select Orifice
            sel_orf = "N/A"; sel_area = 0; sel_letter = ""
            
            # --- UPDATED SELECTION LOGIC ---
            # API 526 Valves: Only select from D to T (api_526_sizes)
            # Non-API Valves: Can select from B to T (all_orifices)
            
            # Filter available orifices based on standard
            if valve_standard == "API 526 (Flanged)":
                # Filter dictionary to only include keys that are in api_526_sizes
                available_orifices = {k: v for k, v in all_orifices.items() if k in api_526_sizes}
            else:
                # Use full dictionary
                available_orifices = all_orifices
            
            # Loop through the filtered list
            for l, a in available_orifices.items():
                if a >= A_final: 
                    sel_orf = f"{l} ({a} mm²)"
                    sel_area = a
                    sel_letter = l
                    break
            
            # For display
            disp_req_area = f"{A_final:.2f} mm²"
            disp_sel_area = f"{sel_area} mm² ({sel_letter})"
            
        else:
            # REVERSE: Find Capacity
            sel_letter = sel_orifice_cap
            sel_area = all_orifices[sel_letter]
            sel_orf = f"{sel_letter} ({sel_area} mm²)"
            A_final = sel_area # For logic consistency
            
            if service_type in ["Gas/Vapor", "Steam"]:
                k_term = (u_k+1)/(u_k-1); C = 520 * np.sqrt(u_k * ((2/(u_k+1))**k_term))
                Kn = 1.0; Ksh = 1.0
                if service_type == "Steam":
                    if P1_sizing > 10443: Kn = (0.276 * (P1_sizing/1000) - 1000) / (0.33 * (P1_sizing/1000) - 1061)
                    if selected_fluid == "Custom (Manual Input)": Ksh = Ksh_manual
                # W = A * C * Kd * P1 * Kb * Kc * Kn * Ksh / (13160 * sqrt(T*Z/M))
                term_sqrt = np.sqrt((T_K * u_Z) / u_Mw)
                W_capacity = (sel_area * C * Kd * P1_sizing * Kb * Kc * Kn * Ksh) / (13160 * term_sqrt)
                formula_used = "W = (A * C * Kd * P1 * Kb * Kc) / (13160 * sqrt(T*Z/M))"

            elif service_type == "Liquid":
                if dP <= 0: st.error("Back Pres > Set Pres!"); st.stop()
                Q_lpm_cap = (sel_area * Kd * Kb * Kc * Kv * np.sqrt(dP)) / (11.78 * np.sqrt(u_SG))
                W_capacity = Q_lpm_cap * 60 * u_SG # kg/hr
                formula_used = "Q = (A * Kd * Kw * Kc * Kv * 11.78 * sqrt(dP/G))"

            elif service_type == "Two-Phase":
                eta_c = calculate_eta_c(u_omega); P_cf = eta_c * P1_sizing; is_critical = P2_abs < P_cf
                v_0 = 1.0 / u_rho; P0 = P1_sizing * 1000
                G_si = eta_c * math.sqrt((P0/v_0)/u_omega) # Simplified
                # W = A * G * Kd...
                A_m2 = sel_area / 1e6
                W_kg_s = A_m2 * G_si * 0.9 * Kd * Kb * Kc
                W_capacity = W_kg_s * 3600
                formula_used = "W = A * G_flux * Kd * Kb * Kc * 0.9"

            # --- UPDATED: Capacity Mode Conversion ---
            W_display = 0.0
            if unit_W == "kg/hr": W_display = W_capacity
            elif unit_W == "lb/hr": W_display = W_capacity / 0.453592
            elif unit_W == "Nm3/hr": W_display = (W_capacity / u_Mw) * 22.414 if u_Mw > 0 else 0
            elif unit_W == "Sm3/hr": W_display = (W_capacity / u_Mw) * 23.64 if u_Mw > 0 else 0
            elif unit_W == "SCFM":
                w_lb = W_capacity / 0.453592
                scfh = (w_lb / u_Mw) * 379.5 if u_Mw > 0 else 0
                W_display = scfh / 60
            elif unit_W == "SCFH":
                w_lb = W_capacity / 0.453592
                W_display = (w_lb / u_Mw) * 379.5 if u_Mw > 0 else 0
            elif unit_W == "LPM": W_display = ((W_capacity / u_Mw) * 22.414) / 0.06 # approx
            elif unit_W == "m3/hr": W_display = (W_capacity / u_SG) / 1000
            elif unit_W == "LPH": W_display = W_capacity / u_SG
            
            disp_req_area = "N/A (Capacity Mode)"
            disp_sel_area = f"{sel_area} mm² ({sel_letter})"
            raw_W = W_display # For PDF Print
            
        # --- DIMENSION LOOKUP ---
        size_str = "Custom"; final_dim_in = c_face_inlet_manual; final_dim_out = c_face_outlet_manual
        if valve_standard == "API 526 (Flanged)":
            if sel_letter in api_526_sizes:
                in_s, out_s = api_526_sizes[sel_letter]; size_str = f"{in_s} x {out_s}"
                found_dims = get_api_dimensions(sel_letter, inlet_rating, outlet_rating)
                if found_dims: final_dim_in, final_dim_out = found_dims; calc_note += " | API Dims found."
                else: calc_note += " | Std API Dims not found."
            else: size_str = "Check API Std"
        else: size_str = f"{sel_inlet_sz} x {sel_outlet_sz}"

        # --- UI DISPLAY ---
        c1, c2, c3 = st.columns(3)
        if calc_mode == "Sizing (Find Orifice)":
            c1.success(f"Required Area: **{A_final:.2f} mm²**")
        else:
            c1.success(f"Rated Capacity: **{raw_W:.2f} {unit_W}**")
            
        c2.metric("Selected Orifice", sel_orf)
        c3.metric("Valve Size", size_str)
        if valve_standard == "API 526 (Flanged)": st.info(f"📏 **Dimensions:** Inlet C-to-F: {final_dim_in} mm | Outlet C-to-F: {final_dim_out} mm")

        # --- DATA PACKING ---
        proj_d = {"Customer": customer, "Tag No": tag_no, "Enquiry No": enquiry_no, "Offer No": offer_no, "Description": desc, "Service": service_type}
        
        flow_label = "Required Flow" if calc_mode == "Sizing (Find Orifice)" else "Rated Capacity"
        
        proc_d = {"Fluid": selected_fluid, flow_label: f"{raw_W:.2f} {unit_W}", "Set Pressure": f"{raw_P1} {unit_P1}", "Constant Back Pressure": f"{raw_BP_const} {unit_BP_const}", "Variable Back Pressure": f"{raw_BP_var} {unit_BP_var}", "Total Back Pressure": f"{raw_BP_const+raw_BP_var:.2f} {unit_BP_const}", "Relieving Temp": f"{raw_T1} {unit_T1}", "Overpressure": f"{overpressure_pct} Accumulation"}
        
        prop_d = {}; prop_d.update({"Kd": f"{Kd}", "Kb": f"{Kb}", "Kc": f"{Kc}"})
        if service_type == "Two-Phase": prop_d.update({"Quality (x)": f"{input_quality}", "Omega (w)": f"{u_omega:.3f}", "Inlet Density": f"{u_rho:.1f} kg/m3"})
        else: prop_d.update({"MW": f"{u_Mw:.2f}", "k (Cp/Cv)": f"{u_k:.3f}", "Z Factor": f"{u_Z:.3f}", "Specific Gravity": f"{u_SG:.3f}", "Viscosity": f"{u_visc:.3f} cP" if service_type=="Liquid" else "N/A"})
        
        mech_d = {"Type": valve_standard, "Valve Size": size_str, "Orifice": sel_letter, "Body Material": body_mat, "Nozzle Material": nozzle_mat, "Disc Material": disc_mat, "Spring Material": spring_mat, "Bellows": "Yes" if bellows else "No", "Lever": lever_type, "Inlet Conn": inlet_str, "Outlet Conn": outlet_str, "Center to Face (Inlet)": f"{final_dim_in} mm", "Center to Face (Outlet)": f"{final_dim_out} mm"}
        
        res_d = {"Calculated Area": disp_req_area, "Selected Area": disp_sel_area, "Sizing Basis": "API 520 (Omega)" if service_type=="Two-Phase" else "API 520 Part I", "Note": calc_note, "Formula Used": formula_used}

        pdf_data = create_datasheet(proj_d, proc_d, prop_d, mech_d, res_d)
        st.session_state.project_log.append({"Tag": tag_no, "Size": size_str, "Orifice": sel_letter, "Service": service_type, "PDF_Bytes": pdf_data})
        if can_download: st.download_button("📥 Download SGM Datasheet", pdf_data, f"{tag_no}_Datasheet.pdf", "application/pdf")
        else: st.warning("🔒 Download Restricted. Contact Admin.")

    except Exception as e: st.error(f"Error: {e}")

st.markdown("---")
if st.session_state.project_log:
    disp_df = pd.DataFrame(st.session_state.project_log).drop(columns=["PDF_Bytes"], errors="ignore")
    st.dataframe(disp_df)
    if can_download:
        if st.button("📦 Download All Datasheets (ZIP)"):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for item in st.session_state.project_log:
                    zf.writestr(f"{item['Tag']}_Datasheet.pdf", item['PDF_Bytes'])
            st.download_button("⬇️ Click to Download Bundle", zip_buffer.getvalue(), "Project_Datasheets.zip", "application/zip")
