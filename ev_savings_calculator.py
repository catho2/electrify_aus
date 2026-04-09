"""
EV Savings Calculator
=====================
Streamlit app that calculates how much a user saves by switching to an EV,
based on their state + area type (metro/regional), and annual mileage.

Setup:
    pip install streamlit pandas

Usage:
    streamlit run ev_savings_calculator.py
"""

import streamlit as st
import pandas as pd
import re
import textwrap
from datetime import datetime

# ── Benchmarks ────────────────────────────────────────────────────────────────

car_benchmarks = {
    "Small car (e.g. Toyota Corolla)": {"litres_per_100km": 6.2,  "fuel": "petrol"},
    "Medium car (e.g. Mazda 6)":       {"litres_per_100km": 7.5,  "fuel": "petrol"},
    "Large car (e.g. Toyota Camry)":   {"litres_per_100km": 8.1,  "fuel": "petrol"},
    "Small SUV (e.g. Mazda CX-30)":    {"litres_per_100km": 6.3,  "fuel": "petrol"},
    "Medium SUV (e.g. Mazda CX-5)":    {"litres_per_100km": 7.2,  "fuel": "petrol"},
    "Large SUV (e.g. Toyota RAV4)":    {"litres_per_100km": 8.4,  "fuel": "petrol"},
    "Large 4WD (e.g. LandCruiser)":    {"litres_per_100km": 11.5, "fuel": "petrol"},
    "Ute (e.g. HiLux / Ranger)":       {"litres_per_100km": 9.5,  "fuel": "petrol"},
    "Diesel SUV (e.g. Prado)":         {"litres_per_100km": 9.5,  "fuel": "diesel"},
    "Diesel ute (e.g. HiLux diesel)":  {"litres_per_100km": 8.5,  "fuel": "diesel"},
    "Diesel wagon (e.g. Everest)":     {"litres_per_100km": 8.0,  "fuel": "diesel"},
}

ev_benchmarks = {
    "EV small (e.g. MG4)":           {"kwh_per_100km": 15.0},
    "EV medium (e.g. BYD Atto 3)":   {"kwh_per_100km": 17.0},
    "EV large (e.g. Tesla Model Y)":  {"kwh_per_100km": 16.5},
    "EV ute (e.g. LDV eT60)":        {"kwh_per_100km": 28.0},
}


# Maps state abbreviation → AIP "State" column value
STATE_TO_AIP = {
    "NSW": "NSW ACT",
    "ACT": "NSW ACT",
    "VIC": "Victoria",
    "QLD": "Queensland",
    "SA":  "South Australia",
    "WA":  "Western Australia",
    "TAS": "Tasmania",
    "NT":  "Northern Territory",
}
 
# Maps state abbreviation → metro location name in AIP data
STATE_TO_METRO_LOCATION = {
    "NSW": "Sydney",
    "ACT": "Canberra",
    "VIC": "Melbourne",
    "QLD": "Brisbane",
    "SA":  "Adelaide",
    "WA":  "Perth",
    "TAS": "Hobart",
    "NT":  "Darwin",
}
 
# Maps state abbreviation → regional location name in AIP data
STATE_TO_REGIONAL_LOCATION = {
    "NSW": "NSW Regional Average",
    "ACT": "NSW Regional Average",
    "VIC": "Victorian Regional Average",
    "QLD": "Queensland Regional Average",
    "SA":  "South Australian Regional Average",
    "WA":  "Western Australian Regional Average",
    "TAS": "Tasmanian Regional Average",
    "NT":  "Northern Territory Regional Average",
}
 
# States we have electricity data for
STATES_WITH_ELEC = ["NSW", "ACT", "QLD", "SA", "TAS"]
ALL_STATES = ["NSW", "ACT", "VIC", "QLD", "SA", "WA", "TAS", "NT"]
 
# ── Data loading ──────────────────────────────────────────────────────────────
 
@st.cache_data
def load_electricity(path: str = "electricity_rates.csv") -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"postcode": str})
    df["area_type"] = df["area_type"].str.strip().str.lower()
    df["state"]     = df["state"].str.strip().str.upper()
    return df
 
@st.cache_data
def load_fuel_prices(path: str) -> tuple[pd.DataFrame, datetime.date | None]:
    """
    Load AIP fuel CSV and extract week ending date from column headers.
    Returns (clean_df, week_date)
    """

    if path.endswith(".xlsx"):
        raw = pd.read_excel(path)
    else:
        raw = pd.read_csv(path)

    # --- Extract week ending date from column names ---
    week_date = None
    for col in raw.columns:
        if isinstance(col, str) and "Week ending" in col:
            clean = re.sub(r"Week ending.*?,\s*", "", col)
            clean = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", clean)
            week_date = datetime.strptime(clean, "%d %B %Y").date()
            break

    # --- Re-read clean (your existing logic) ---
    if path.endswith(".xlsx"):
        df = pd.read_excel(path, header=None)
    else:
        df = pd.read_csv(path, header=None)

    df.columns = ["State", "Week_Ending", "Location", "Weekly_Average",
                  "Weekly_Change", "Variation", "Weekly_Low", "Weekly_High"]

    df = df[~df["State"].isin(["State", None]) & df["State"].notna()]
    df = df[df["Location"].notna() & (df["Location"] != "Location")]

    df["Weekly_Average"] = pd.to_numeric(df["Weekly_Average"], errors="coerce")
    df = df.dropna(subset=["Weekly_Average"])

    return df, week_date
 
 
def get_electricity_rate(df: pd.DataFrame, state: str, area_type: str) -> float | None:
    rows = df[(df["state"] == state) & (df["area_type"] == area_type)]
    if rows.empty:
        return None
    return round(rows["rate_cents"].mean(), 1)
 
 
def get_fuel_price(df: pd.DataFrame, state: str, area_type: str) -> tuple[float | None, str]:
    """Return (price_cpl, location_name) for a state + area type."""
    aip_state = STATE_TO_AIP.get(state)
    if not aip_state:
        return None, ""
 
    if area_type == "metro":
        location = STATE_TO_METRO_LOCATION.get(state)
    else:
        location = STATE_TO_REGIONAL_LOCATION.get(state)
 
    if not location:
        return None, ""
 
    rows = df[(df["State"] == aip_state) & (df["Location"] == location)]
    if rows.empty:
        return None, location
 
    price = rows["Weekly_Average"].iloc[0]
    return round(float(price), 1), location
 
 
# ── Calculations ──────────────────────────────────────────────────────────────
 
def calc_fuel_cost(litres_per_100km: float, price_cpl: float, km: float) -> float:
    return (litres_per_100km / 100) * km * (price_cpl / 100)
 
 
def calc_ev_cost(kwh_per_100km: float, rate_cents: float, km: float) -> float:
    return (kwh_per_100km / 100) * km * (rate_cents / 100)
 
 
# ── Page config ───────────────────────────────────────────────────────────────
 
st.set_page_config(
    page_title="EV Savings Calculator 🇦🇺",
    page_icon="⚡",
    layout="centered",
)
 
st.title("⚡ EV Savings Calculator")
st.markdown(
    "Find out how much you could save annually by switching to an electric vehicle in Australia, "
    "based on your location's electricity rate and your state's current fuel price (where available)."
)

st.markdown(
    """
    <style>
    .bmc-float {
        position: fixed;
        bottom: 80px;
        right: 0;
        z-index: 9999;
        writing-mode: vertical-rl;
        text-orientation: mixed;
        background-color: #FFDD00;
        color: #000000;
        font-size: 12px;
        font-weight: 600;
        font-family: sans-serif;
        padding: 12px 6px;
        border-radius: 8px 0 0 8px;
        text-decoration: none;
        box-shadow: -2px 2px 6px rgba(0,0,0,0.2);
        transition: padding 0.2s ease;
    }
    .bmc-float:hover {
        padding: 12px 10px;
        color: #000000;
    }
    </style>
    <a class="bmc-float" href="https://www.buymeacoffee.com/YOUR_USERNAME" target="_blank">
        ☕ Buy me a coffee
    </a>
    """,
    unsafe_allow_html=True,
)
 
# ── Load data ─────────────────────────────────────────────────────────────────
 
try:
    elec_df = load_electricity()
except FileNotFoundError:
    st.error("❌ Could not find `electricity_rates.csv`. Place it in the same folder as this script.")
    st.stop()
 
try:
    petrol_df, petrol_week = load_fuel_prices("aip_petrol_prices.csv")
except FileNotFoundError:
    st.error("❌ Could not find `aip_petrol_prices.csv`. Place it in the same folder as this script.")
    st.stop()
 
try:
    diesel_df, diesel_week = load_fuel_prices("aip_diesel_prices.csv")
except FileNotFoundError:
    st.error("❌ Could not find `aip_diesel_prices.csv`. Place it in the same folder as this script.")
    st.stop()

 
# ── Inputs ────────────────────────────────────────────────────────────────────
 
st.header("1. Your location")
 
col1, col2 = st.columns(2)
 
with col1:
    state = st.selectbox(
        "State / territory",
        options=["— Select —"] + ALL_STATES,
    )
 
with col2:
    area_type = st.selectbox(
        "Area type",
        options=["— Select —", "Metro", "Regional"],
        disabled=(state == "— Select —"),
        help="Metro = capital city area. Regional = outside the metro area.",
    )
 
# Live preview of rates once both selected
if state != "— Select —" and area_type != "— Select —":
    area_key = area_type.lower()
 
    # Electricity preview
    if state in STATES_WITH_ELEC:
        elec_preview = get_electricity_rate(elec_df, state, area_key)
        if elec_preview:
            st.caption(f"📍 Electricity rate for {area_type} {state}: **{elec_preview:.1f} c/kWh**")
        else:
            st.caption(f"📍 No electricity data for {area_type} {state} — you can enter a custom rate below.")
    else:
        st.caption(f"📍 No electricity data for {state} yet — enter a custom rate below.")
 
    # Petrol price preview
    petrol_preview, petrol_loc = get_fuel_price(petrol_df, state, area_key)
    if petrol_preview:
        st.caption(f"⛽ Latest petrol price for {petrol_loc}: **{petrol_preview:.1f} c/L**")
            
    # Diesel preview 
    diesel_preview, diesel_loc = get_fuel_price(diesel_df, state, area_key)
    if diesel_preview:
        st.caption(f"🚛 Latest diesel price for {diesel_loc}: **{diesel_preview:.1f} c/L**")

    if petrol_week:
        st.caption(f" ⏲ Fuel prices updated: **Week ending {petrol_week.strftime('%d %b %Y')}**")


 
st.header("2. Your driving")
 
annual_km = st.slider(
    "Annual kilometres driven",
    min_value=5_000,
    max_value=100_000,
    value=15_000,
    step=1_000,
    format="%d km",
)
 
st.header("3. Your current car")
current_car = st.selectbox("What kind of car do you drive?", options=list(car_benchmarks.keys()))
 
detected_fuel = car_benchmarks[current_car]["fuel"]
st.info(f"⛽ Detected fuel type: **{detected_fuel.capitalize()}**")
 
st.header("4. EV you're considering")
ev_car = st.selectbox("Which EV are you comparing against?", options=list(ev_benchmarks.keys()))

week_date = petrol_week if detected_fuel == "petrol" else diesel_week
 
# ── Optional overrides ────────────────────────────────────────────────────────
 
with st.expander("⚙️ Override prices (optional)"):
    st.markdown("Leave at 0 to use live data for your selected location.")
    custom_elec = st.number_input("Electricity rate (c/kWh)", min_value=0.0, value=0.0, step=0.1)
    custom_fuel = st.number_input("Fuel price (c/L)",         min_value=0.0, value=0.0, step=0.1)
 
# ── Calculate ─────────────────────────────────────────────────────────────────
 
calculate_disabled = (state == "— Select —" or area_type == "— Select —")
 
if st.button("Calculate my savings ⚡", type="primary", disabled=calculate_disabled):
 
    area_key = area_type.lower()
 
    # -- Electricity rate
    if custom_elec > 0:
        elec_rate   = custom_elec
        elec_source = f"custom ({elec_rate:.1f} c/kWh)"
    else:
        elec_rate = get_electricity_rate(elec_df, state, area_key)
        if elec_rate is None:
            st.error(
                f"No electricity data found for {area_type} {state}. "
                "Please enter a custom electricity rate in the override section above."
            )
            st.stop()
        elec_source = f"{area_type} {state} ({elec_rate:.1f} c/kWh)"
 
    # -- Fuel price
    fuel_label = detected_fuel.capitalize()
 
    if custom_fuel > 0:
        fuel_price  = custom_fuel
        fuel_source = f"custom ({fuel_price:.1f} c/L)"
    else:
        if detected_fuel == "petrol":
            fuel_price, fuel_loc = get_fuel_price(petrol_df, state, area_key)
        else:
            if diesel_df is None:
                st.error(
                    "No diesel price data found (`aip_diesel_prices.csv`). "
                    "Please enter a custom diesel price in the override section above."
                )
                st.stop()
            fuel_price, fuel_loc = get_fuel_price(diesel_df, state, area_key)
 
        if fuel_price is None:
            st.error(
                f"No {detected_fuel} price found for {area_type} {state}. "
                "Please enter a custom price in the override section above."
            )
            st.stop()
        fuel_source = f"{fuel_loc} ({fuel_price:.1f} c/L)"
 
    # -- Costs
    litres      = car_benchmarks[current_car]["litres_per_100km"]
    kwh         = ev_benchmarks[ev_car]["kwh_per_100km"]
    fuel_annual = calc_fuel_cost(litres, fuel_price, annual_km)
    ev_annual   = calc_ev_cost(kwh, elec_rate, annual_km)
    savings     = fuel_annual - ev_annual
 
    # ── Results ───────────────────────────────────────────────────────────────
 
    st.divider()
    st.header("Your results")

    col_a, col_b, col_c = st.columns(3)

    col_a.metric(f"⛽ {fuel_label} annual cost", f"${fuel_annual:,.0f}")
    col_b.metric("⚡ EV annual cost", f"${ev_annual:,.0f}")
    col_c.metric(
        "💰 Annual saving",
        f"${abs(savings):,.0f}",
        delta=f"{'Save' if savings > 0 else 'Extra cost'} ${abs(savings/12):,.0f}/month",
        delta_color="normal" if savings > 0 else "inverse",
)

    if savings > 0:
        msg = (
            f"🎉 Switching from a **{current_car}** to a **{ev_car}** could save you "
            f"**${savings:,.0f} per year** driving **{annual_km:,} km**. \n\n"
    )
        st.success(msg)

    else:
        msg = (
            f"With current prices, the EV would cost **${abs(savings):,.0f} more per year** to run.\n\n"
            "Try adjusting your inputs or check back as fuel prices change."
    )
        st.info(msg)
 
    # 5-year projection
    st.subheader("5-year projection")
    projection_rows = []
    for yr in range(1, 6):
            projection_rows.append({
                "Year":                    f"Year {yr}",
                f"{fuel_label} total ($)": f"${fuel_annual * yr:,.0f}",
                "EV total ($)":            f"${ev_annual * yr:,.0f}",
                "Cumulative saving ($)":   f"${savings * yr:,.0f}",
        })
    st.table(pd.DataFrame(projection_rows).set_index("Year"))
    st.divider()
    st.caption(
            f"📊 **Data sources:** Electricity — {elec_source} is the median price of {elec_source} from AER's Energy Made Easy website. "
            f"{fuel_label} price — {fuel_source} is based on Australian Institute of Petroleum's reports from week ending {week_date.strftime("%d %b %Y") if week_date else 'latest available'}. "
            f"Fuel efficiency based on industry benchmarks.\n\n"

            f"This is just an experiment! There are lots of things that don't work here but I thought something is better than none"
    )

 
elif calculate_disabled:
    st.caption("👆 Please select your state and area type to continue.")
