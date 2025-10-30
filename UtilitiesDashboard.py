import streamlit as st
import requests
import certifi
import json
from datetime import datetime, timedelta, date
import math
import csv
import io
import urllib3
import sys
# New imports for scraping
from bs4 import BeautifulSoup
import re

# --- 1. PYTHON DATA FETCHING LOGIC ---

# --- Weather Fetching ---
FORECAST_URL = 'https://api.open-meteo.com/v1/forecast?latitude=51.90,52.14&longitude=-8.47,-10.27&current=temperature_2m&daily=time,weathercode,temperature_2m_max,temperature_2m_min,wind_speed_10m_max,wind_gusts_10m_max&timezone=Europe%2FDublin&forecast_days=3'
ALERTS_CORK_URL = 'https://meteo-api.open-meteo.com/v1/meteoalerts?latitude=51.90&longitude=-8.47&domains=met&forecast_days=3'
ALERTS_KERRY_URL = 'https://meteo-api.open-meteo.com/v1/meteoalerts?latitude=52.14&longitude=-10.27&domains=met&forecast_days=3'

# --- TIDE SCRAPING FUNCTIONS (from user) ---

def get_day_suffix(day):
    """Returns the ordinal suffix (st, nd, rd, th) for a given day."""
    if 10 <= day % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
    return suffix

def scrape_tide_times(location, url, target_days):
    """
    Scrapes tide times for a single location.

    Args:
        location (str): The name of the location (e.g., "Cork").
        url (str): The URL to scrape.
        target_days (list): A list of strings for the target days.
    
    Returns:
        dict: A dictionary of tide data for the target days, or None on failure.
    """
    # Set a user-agent to mimic a browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    print(f"--- [DEBUG] Scraping tide times for {location} ---", file=sys.stderr)
    try:
        # Fetch the webpage, disabling SSL verification
        response = requests.get(url, headers=headers, verify=False)
        print(f"--- [DEBUG] {location} response status: {response.status_code} ---", file=sys.stderr)
        response.raise_for_status()  # Raise an error for bad responses

        # Parse the HTML
        soup = BeautifulSoup(response.text, 'html.parser')

        # Find the specific tide table by its ID
        table = soup.find(id="tide-table")

        if not table:
            print(f"--- [DEBUG] Could not find table with id='tide-table' for {location}. Structure may have changed. ---", file=sys.stderr)
            return None
        print(f"--- [DEBUG] Found 'tide-table' for {location}. ---", file=sys.stderr)

        # --- New, more robust table parsing logic ---
        
        # 1. Find Headers (<th>)
        # Try to find headers in <thead>, else in the first <tr>
        thead = table.find('thead')
        header_row = thead.find('tr') if thead else table.find('tr')
        
        if not header_row:
            print(f"--- [DEBUG] Could not find header row <tr> for {location}. ---", file=sys.stderr)
            return None
        headers = header_row.find_all('th')

        # 2. Find Data Cells (<td>)
        # Try to find data cells in <tbody>
        tbody = table.find('tbody')
        data_row = tbody.find('tr') if tbody else None
        
        # If no <tbody>, try to find the *next* <tr> after the header row
        if not data_row and header_row:
            next_row = header_row.find_next_sibling('tr')
            if next_row:
                data_row = next_row
            else:
                # Fallback: find all <tr>s and take the second one
                all_rows = table.find_all('tr')
                if len(all_rows) > 1:
                    data_row = all_rows[1] # Assume data is in the second row
        
        if not data_row:
            print(f"--- [DEBUG] Could not find data row <tr> for {location}. ---", file=sys.stderr)
            return None
            
        data_cells = data_row.find_all('td')
        # --- End of new logic ---

        if not headers or not data_cells or len(headers) != len(data_cells):
            print(f"--- [DEBUG] Table structure mismatch for {location}. Found {len(headers)} headers and {len(data_cells)} cells. ---", file=sys.stderr)
            return None
        print(f"--- [DEBUG] {location} - Headers: {len(headers)}, Cells: {len(data_cells)} ---", file=sys.stderr)


        # Map days to their tide data
        daily_data = {}
        for i, header_cell in enumerate(headers):
            if i < len(data_cells):
                # Clean the day text (e.g., "Wed, 29th")
                day_name = " ".join(header_cell.text.split())
                
                # Get the text from the corresponding data cell
                panel_text = data_cells[i].get_text(separator=' ', strip=True)
                
                # Use regex to find all tide events (Low/High time (height))
                tides = re.findall(r"(Low|High) (\d{2}:\d{2}[ap]m) \((\d+\.\d+m)\)", panel_text)
                
                # Format the tide data
                tide_events = []
                for tide in tides:
                    # New format: <b>Low</b> 05:33am (2.02m)
                    tide_events.append(f"<b>{tide[0]}</b> {tide[1]} ({tide[2]})")
                
                # Join with " | "
                daily_data[day_name] = " | ".join(tide_events)

        print(f"--- [DEBUG] {location} - Raw Scraped Data: {daily_data} ---", file=sys.stderr)

        # Filter for the target days
        location_tides = {}
        for day in target_days:
            if day in daily_data:
                location_tides[day] = daily_data[day]
            else:
                location_tides[day] = "Data not found"
        
        print(f"--- [DEBUG] {location} - Filtered Data: {location_tides} ---", file=sys.stderr)
        return location_tides

    except requests.exceptions.RequestException as e:
        print(f"Error fetching page for {location}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An error occurred while processing {location}: {e}", file=sys.stderr)
        
    return None

@st.cache_data(ttl=60) # Cache for 1 minute
def fetch_scraped_tides():
    """Fetches tide data from tidetime.org for Cork and Kerry."""
    
    locations_to_scrape = {
        "Cork": "https://www.tidetime.org/europe/ireland/cork.htm",
        "Kerry (Fenit)": "https://www.tidetime.org/europe/ireland/fenit.htm"
    }

    # --- Generate Dynamic Target Days ---
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    next_day = today + timedelta(days=2)

    # Helper function to format the date just like the website
    # e.g., "Thu, 30th"
    day_format = lambda dt: f"{dt.strftime('%a')}, {dt.day}{get_day_suffix(dt.day)}"

    target_days_list = [day_format(today), day_format(tomorrow), day_format(next_day)]
    print(f"--- [DEBUG] Targeting days: {', '.join(target_days_list)} ---", file=sys.stderr)
    # --- End of Dynamic Days ---

    all_scraped_data = {}
    for location, url in locations_to_scrape.items():
        tide_data = scrape_tide_times(location, url, target_days_list)
        if tide_data:
            all_scraped_data[location] = tide_data
        else:
            # Ensure a fallback empty dict so JS doesn't break
            print(f"--- [DEBUG] Scrape failed for {location}. Using fallback. ---", file=sys.stderr)
            all_scraped_data[location] = {day: "Data unavailable" for day in target_days_list}

    return all_scraped_data


# --- Modified Weather Fetching Function ---
@st.cache_data(ttl=60) # Cache for 1 minute
def fetch_all_weather():
    """Fetches weather data from Open-Meteo."""
    try:
        with requests.Session() as s:
            # Use verify=False to bypass SSL errors in corporate environments
            forecast_res = s.get(FORECAST_URL, verify=False)
            alerts_cork_res = s.get(ALERTS_CORK_URL, verify=False)
            alerts_kerry_res = s.get(ALERTS_KERRY_URL, verify=False)

            forecast_res.raise_for_status()
            alerts_cork_res.raise_for_status()
            alerts_kerry_res.raise_for_status()

            return {
                "forecasts": forecast_res.json(),
                "alertsCork": alerts_cork_res.json(),
                "alertsKerry": alerts_kerry_res.json(),
            }
    except requests.exceptions.RequestException as e:
        print(f"Error fetching weather data: {e}", file=sys.stderr)
        
        # --- Create dynamic dummy data for forecasts ---
        today = date.today()
        dummy_dates = [(today + timedelta(days=i)).strftime('%Y-%m-%d') for i in range(3)]
        
        dummy_forecasts = [
            { 
                "current": { "temperature_2m": 15.1 }, 
                "daily": { 
                    "time": dummy_dates, # <-- Use dynamic dates
                    "weathercode": [3, 61, 3], 
                    "temperature_2m_max": [17, 18, 16], 
                    "temperature_2m_min": [10, 11, 9], 
                    "wind_speed_10m_max": [15, 18, 20], 
                    "wind_gusts_10m_max": [30, 35, 40] 
                } 
            },
            { 
                "current": { "temperature_2m": 14.6 }, 
                "daily": { 
                    "time": dummy_dates, # <-- Use dynamic dates
                    "weathercode": [61, 3, 61], 
                    "temperature_2m_max": [16, 17, 15], 
                    "temperature_2m_min": [9, 10, 8], 
                    "wind_speed_10m_max": [20, 22, 25], 
                    "wind_gusts_10m_max": [40, 45, 50] 
                } 
            }
        ]

        return {
            "forecasts": dummy_forecasts,
            "alertsCork": { "alerts": [
                { "headline": "Yellow Wind Warning for Cork", "severity": "Moderate", "event": "Wind", "start": "2025-10-30T06:00", "end": "2025-10-30T18:00" }
            ] },
            "alertsKerry": { "alerts": [] },
        }

# --- Jotform Data Fetching (No Pandas) ---
@st.cache_data(ttl=60) # Cache for 1 minute
def fetch_jotform_data():
    """Fetches and processes CSV data from Jotform using the csv module."""
    url = "https://eu.jotform.com/csv/253023071318042"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
    }
    
    # Suppress only the InsecureRequestWarning from urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    data_list = []
    
    try:
        response = requests.get(url, headers=headers, verify=False)
        response.raise_for_status()
        
        csv_data = io.StringIO(response.text)
        reader = csv.DictReader(csv_data)
        
        for row in reader:
            # Clean and map data
            priority_val = row.get('Priority')
            if isinstance(priority_val, str):
                priority_num = int(''.join(filter(str.isdigit, priority_val)) or 0)
            elif isinstance(priority_val, (int, float)):
                priority_num = int(priority_val)
            else:
                priority_num = 0

            # Handle potential None for Lat/Lon
            lat = row.get('Lat')
            lon = row.get('Lon')
            
            processed_row = {
                "Date": row.get('Date', ''),
                "FirstName": row.get('First Name', ''),
                "LastName": row.get('Last Name', ''),
                "Facility": row.get('HSE Facility', ''),
                "Lat": float(lat) if lat else None,
                "Lon": float(lon) if lon else None,
                "Location": row.get('Exact Location of Issue', ''),
                "Utility": row.get('Type of Utility Affected', 'Other'),
                "Description": row.get('Description', ''),
                "Priority": priority_num,
                "Phone": row.get('Phone Number', ''),
                "Email": row.get('Email', ''),
                "Status": row.get('Status', 'Ongoing'),
                "PriorityAfterStatus": row.get('Priority After Status', None)
            }
            data_list.append(processed_row)
        
        # print(f"Successfully fetched and processed {len(data_list)} records from Jotform.", file=sys.stderr)
        return json.dumps(data_list)

    except requests.exceptions.HTTPError as http_err:
        print(f"An HTTP error occurred: {http_err}", file=sys.stderr)
    except Exception as e:
        print(f"An error occurred fetching Jotform data: {e}", file=sys.stderr)
    
    # Return an empty list as a JSON string on failure
    return "[]"

# --- 2. ENHANCED HTML TEMPLATE ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>HSE Utility Dashboard</title>
    <link rel="icon" href="https://www.hse.ie/favicon-32x32.png" type="image/png">
    
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@3.9.1/dist/chart.min.js"></script>

    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        
        :root {
            --hse-teal: #02594C;
            --hse-teal-light: #037362;
            --hse-wine: #8B1538;
            --primary-gradient: linear-gradient(135deg, #02594C 0%, #014D42 100%);
            --glass-bg: rgba(255, 255, 255, 0.85);
            --glass-border: rgba(255, 255, 255, 0.3);
        }
        
        * {
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }
        
        body {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: linear-gradient(135deg, #f0f4f8 0%, #d9e2ec 100%);
            background-attachment: fixed;
            min-height: 100vh;
            position: relative;
        }
        
        body::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-image: 
                radial-gradient(circle at 20% 50%, rgba(2, 89, 76, 0.03) 0%, transparent 50%),
                radial-gradient(circle at 80% 80%, rgba(139, 21, 56, 0.03) 0%, transparent 50%);
            pointer-events: none;
            z-index: 0;
        }
        
        .content-wrapper {
            position: relative;
            z-index: 1;
            max-width: 1600px;
            margin: 0 auto;
        }
        
        #map {
            height: 45vh; /* <-- Desktop map height */
            border-radius: 1rem;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.15);
            z-index: 10;
            border: 3px solid rgba(255, 255, 255, 0.5);
            backdrop-filter: blur(10px);
        }
        
        .pro-card {
            background: var(--glass-bg);
            backdrop-filter: blur(20px);
            border: 1px solid var(--glass-border);
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            position: relative;
            overflow: hidden;
        }
        
        .pro-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 3px;
            background: linear-gradient(90deg, transparent, var(--hse-teal), transparent);
            transform: translateX(-100%);
            transition: transform 0.6s ease;
        }
        
        .pro-card:hover::before {
            transform: translateX(100%);
        }
        
        .pro-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 25px 50px -12px rgba(2, 89, 76, 0.25);
            border-color: rgba(2, 89, 76, 0.3);
        }
        
        .stat-number {
            font-feature-settings: 'tnum';
            font-variant-numeric: tabular-nums;
            letter-spacing: -0.05em;
        }
        
        @keyframes shimmer {
            0% { transform: translateX(-100%); }
            100% { transform: translateX(100%); }
        }
        
        .loading-shimmer {
            position: relative;
            overflow: hidden;
        }
        
        .loading-shimmer::after {
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            bottom: 0;
            left: 0;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.4), transparent);
            animation: shimmer 2s infinite;
        }
        
        @keyframes ticker {
            0% { transform: translateX(100%); }
            100% { transform: translateX(-100%); }
        }
        
        .ticker-wrap {
            overflow: hidden;
            background: linear-gradient(90deg, rgba(239,68,68,0.15) 0%, rgba(239,68,68,0.05) 50%, rgba(239,68,68,0.15) 100%);
            backdrop-filter: blur(10px);
            border: 2px solid rgba(239, 68, 68, 0.3);
        }
        
        .ticker {
            display: inline-block;
            white-space: nowrap;
            animation: ticker 30s linear infinite;
            padding-right: 100%;
        }
        
        .pro-button {
            position: relative;
            overflow: hidden;
            font-weight: 600;
            letter-spacing: 0.025em;
            text-transform: uppercase;
            font-size: 0.75rem;
        }
        
        .pro-button::before {
            content: '';
            position: absolute;
            top: 50%;
            left: 50%;
            width: 0;
            height: 0;
            border-radius: 50%;
            background: rgba(255,255,255,0.3);
            transform: translate(-50%, -50%);
            transition: width 0.6s, height 0.6s;
        }
        
        .pro-button:hover::before {
            width: 300px;
            height: 300px;
        }
        
        .chart-bar {
            transition: all 0.8s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .header-gradient {
            background: var(--primary-gradient);
            box-shadow: 0 10px 40px -10px rgba(2, 89, 76, 0.4);
            border-bottom: 4px solid var(--hse-teal-light);
        }
        
        .icon-container {
            background: rgba(255, 255, 255, 0.15);
            backdrop-filter: blur(10px);
            transition: all 0.3s ease;
        }
        
        .icon-container:hover {
            background: rgba(255, 255, 255, 0.25);
            transform: scale(1.05);
        }
        
        .modal-backdrop {
            backdrop-filter: blur(8px);
            background: rgba(0, 0, 0, 0.6);
        }
        
        .priority-badge {
            display: inline-flex;
            align-items: center;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 0.75rem;
            letter-spacing: 0.025em;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }
        
        @media (max-width: 768px) {
            #map {
                height: 25vh; /* <-- Mobile map height */
            }
        }
        
        .fade-in {
            animation: fadeIn 0.6s ease-in;
        }
        
        @keyframes fadeIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }

        #live-clock {
            line-height: 1.3;
        }

        .data-unavailable {
            font-style: italic;
            color: #9ca3af; /* text-gray-400 */
        }
    </style>
</head>
<body class="p-4 md:p-8">
    <div class="content-wrapper">
        <header class="mb-6 px-4 py-4 sm:px-6 sm:py-5 rounded-2xl shadow-2xl flex flex-col sm:flex-row justify-between items-start sm:items-center header-gradient fade-in">
            <div class="flex flex-col items-center sm:flex-row sm:items-center text-center sm:text-left mb-4 sm:mb-0 w-full sm:w-auto">
                <div class="icon-container p-3 rounded-xl sm:mr-4 mb-3 sm:mb-0 shadow-lg">
                    <img src="https://www.hse.ie/image-library/hse-site-logo-2021.svg" alt="HSE Logo" class="h-14">
                </div>
                <div class="w-full sm:w-auto">
                    <h1 class="text-2xl sm:text-3xl font-black text-white tracking-tight">
                        HSE Facilities Dashboard
                    </h1>
                    <p class="text-teal-100 text-sm mt-1 font-medium">Real-time Infrastructure Monitoring & Safety Management</p>
                </div>
            </div>
            <div class="flex flex-col items-start w-full sm:w-auto sm:items-end space-y-3">
                <div class="flex flex-col sm:flex-row items-start sm:items-center space-y-3 sm:space-y-0 sm:space-x-3">
                    <span class="text-white font-semibold text-xs uppercase tracking-wider">Map View:</span>
                    <button id="mapToggle" class="pro-button px-5 py-2.5 rounded-lg transition-all shadow-lg bg-blue-600 text-white hover:bg-blue-700">
                        By Utility
                    </button>
                    <span class="text-white font-semibold text-xs uppercase tracking-wider ml-0 sm:ml-3">Filter:</span>
                    <button id="toggleButton" class="pro-button px-5 py-2.5 rounded-lg transition-all shadow-lg bg-red-600 text-white hover:bg-red-700">
                        Ongoing Only
                    </button>
                </div>
                <div id="live-clock" class="text-sm font-semibold text-white text-left sm:text-right w-full mt-2"></div>
            </div>
        </header>

        <div id="safetyAlertsTicker" class="mb-6 rounded-2xl overflow-hidden shadow-xl fade-in">
        </div>

        <div class="mb-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6 fade-in"> 
            <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl border-l-4 border-slate-500">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">Total Issues</div>
                        <div id="totalCard" class="stat-number text-5xl font-black text-gray-900 mb-1">0</div>
                        <div class="text-xs text-gray-500 font-medium">Ongoing + Completed</div>
                    </div>
                    <div class="icon-container p-4 rounded-xl bg-slate-100">
                        <svg class="w-8 h-8 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
                    </div>
                </div>
            </div>
            <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl border-l-4 border-red-500">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-xs font-bold text-red-500 uppercase tracking-widest mb-2">Ongoing Issues</div>
                        <div id="ongoingCard" class="stat-number text-5xl font-black text-red-700 mb-1">0</div>
                        <div class="text-xs text-red-500 font-medium">Requires attention</div>
                    </div>
                    <div class="icon-container p-4 rounded-xl bg-red-100">
                        <svg class="w-8 h-8 text-red-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
                    </div>
                </div>
            </div>
            <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl border-l-4 border-green-500">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="text-xs font-bold text-green-500 uppercase tracking-widest mb-2">Completed</div>
                        <div id="completeCard" class="stat-number text-5xl font-black text-green-700 mb-1">0</div>
                        <div class="text-xs text-green-500 font-medium">Successfully resolved</div>
                    </div>
                    <div class="icon-container p-4 rounded-xl bg-green-100">
                        <svg class="w-8 h-8 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                    </div>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 fade-in">
            <div class="lg:col-span-2">
                <div id="map" class="loading-shimmer"></div>
            </div>

            <div class="lg:col-span-1 space-y-6">
                <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl">
                    <h3 class="text-lg font-bold text-gray-800 mb-5 flex items-center">
                        <div class="w-1.5 h-7 bg-blue-500 mr-3 rounded-full shadow-md"></div>
                        Issues by Utility Type
                    </h3>
                    <div id="utilityChart" class="flex flex-col space-y-2">
                    </div>
                </div>

                <div class="pro-card p-4 sm:p-6 rounded-2xl shadow-xl">
                    <h3 class="text-lg font-bold text-gray-800 mb-5 flex items-center">
                        <div class="w-1.5 h-7 bg-orange-500 mr-3 rounded-full shadow-md"></div>
                        Issues by Priority Level
                    </h3>
                    <div id="priorityChartContainer" class="relative" style="height: 250px;">
                        <canvas id="priorityChart"></canvas>
                    </div>
                </div>

                <div class="pro-card bg-gradient-to-br from-gray-50 to-gray-100 p-4 sm:p-6 rounded-2xl shadow-xl border border-gray-200">
                    <h3 class="text-lg font-bold text-gray-800 mb-4 flex items-center">
                        <svg class="w-5 h-5 mr-2 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                        Priority Scale Reference
                    </h3>
                    <ul class="space-y-3 text-sm">
                        <li class="flex items-center font-semibold"><span class="priority-badge bg-red-100 text-red-800 mr-3">P5</span>Critical - Immediate Action Required</li>
                        <li class="flex items-center"><span class="priority-badge bg-orange-100 text-orange-800 mr-3">P3-4</span>High - Urgent Review Needed</li>
                        <li class="flex items-center"><span class="priority-badge bg-yellow-100 text-yellow-800 mr-3">P1-2</span>Low - Scheduled Maintenance</li>
                    </ul>
                </div>
            </div>
        </div>

        <div class="mt-8 pro-card p-4 sm:p-6 rounded-2xl shadow-xl border-l-4 border-blue-400 fade-in">
            <h3 class="text-lg font-bold text-gray-800 mb-5 flex items-center">
                <svg class="w-6 h-6 mr-3 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"/></svg>
                Weather, Tide & Safety Status
            </h3>
            <div id="weatherCardContent" class="text-sm text-gray-600">
                <div class="loading-shimmer h-32 bg-gray-100 rounded-lg"></div>
            </div>
        </div>

        <footer class="mt-12 text-center text-gray-500 text-xs font-medium">
            <p>---</p>
            <p>This dashboard was designed and developed by Dave Maher.</p>
            <p>All associated intellectual property is proprietary.</p>
        </footer>
    </div>

    <div id="modal" class="hidden fixed inset-0 z-50 overflow-y-auto modal-backdrop flex justify-center items-center p-4">
        <div id="modalContent" class="pro-card rounded-2xl shadow-2xl max-w-2xl w-full mx-auto transform transition-all duration-300">
        </div>
    </div>

    <script>
        const PRELOADED_WEATHER_DATA = %%WEATHER_DATA_PLACEHOLDER%%;
        const PRELOADED_TIDE_DATA = %%TIDE_DATA_PLACEHOLDER%%;
        const RAW_DATA = %%JOTFORM_DATA_PLACEHOLDER%%;
        
        const UTILITY_COLORS = {
            'Electricity': { bg: 'bg-red-500', text: 'text-red-600', hex: '#ef4444' },
            'Mechanical': { bg: 'bg-blue-500', text: 'text-blue-600', hex: '#3b82f6' },
            'Medical Gases': { bg: 'bg-green-500', text: 'text-green-600', hex: '#22c55e' },
            'IT/Communication': { bg: 'bg-yellow-500', text: 'text-yellow-600', hex: '#f59e0b' },
            'Water': { bg: 'bg-indigo-500', text: 'text-indigo-600', hex: '#6366f1' },
            'Gas': { bg: 'bg-purple-500', text: 'text-purple-600', hex: '#a855f7' },
            'Other': { bg: 'bg-gray-500', text: 'text-gray-600', hex: '#6b7280' },
        };

        const PRIORITY_COLORS = {
            5: { hex: '#b91c1c' },
            4: { hex: '#f97316' },
            3: { hex: '#f59e0b' },
            2: { hex: '#eab308' },
            1: { hex: '#facc15' },
            0: { hex: '#6b7280' },
            'Other': { hex: '#6b7280' }
        };

        let showComplete = false;
        let mapColorMode = 'utility';
        let mapInstance = null;
        let markersLayer = null;
        let priorityChartInstance = null;

        // --- DOM Element Variables (will be assigned on DOMContentLoaded) ---
        let toggleButton, mapToggle, totalCard, ongoingCard, completeCard;
        let utilityChartEl, priorityChartContainer, priorityChartEl;
        let modalEl, modalContentEl, weatherCardContent;


        function animateNumber(element, target) {
            const start = parseInt(element.textContent) || 0;
            const duration = 1000;
            const startTime = performance.now();
            
            function update(currentTime) {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const easeOut = 1 - Math.pow(1 - progress, 3);
                const current = Math.floor(start + (target - start) * easeOut);
                element.textContent = current;
                
                if (progress < 1) {
                    requestAnimationFrame(update);
                }
            }
            
            requestAnimationFrame(update);
        }

        function updateDashboard() {
            // Filter only affects map and charts
            const filteredData = RAW_DATA.filter(issue => showComplete || issue.Status === 'Ongoing');
            
            // Scorecards are based on ALL data, not filtered data
            updateScoreCards(); 
            
            updateCharts(filteredData);
            updateMap(filteredData);
            animateChartBars(); // Animate bars after they are drawn
        }

        function updateScoreCards() {
            // Calculate totals from the full RAW_DATA set
            const ongoing = RAW_DATA.filter(i => i.Status === 'Ongoing').length;
            const totalCompleteCount = RAW_DATA.filter(i => i.Status === 'Complete').length;
            const totalIssues = ongoing + totalCompleteCount;
            
            animateNumber(totalCard, totalIssues);
            animateNumber(ongoingCard, ongoing);
            animateNumber(completeCard, totalCompleteCount);
        }

        function updateCharts(data) {
            const utilityCounts = data.reduce((acc, issue) => {
                const utility = issue.Utility || 'Other';
                acc[utility] = (acc[utility] || 0) + 1;
                return acc;
            }, {});
            const utilityChartData = Object.entries(utilityCounts)
                .map(([name, value])=> ({ name, value, color: UTILITY_COLORS[name]?.hex || UTILITY_COLORS['Other'].hex }))
                .sort((a, b) => b.value - a.value);
            
            utilityChartEl.innerHTML = generateBarChartHTML(utilityChartData);

            const priorityCounts = data.reduce((acc, issue) => {
                const p = `P${issue.Priority || 0}`;
                acc[p] = (acc[p] || 0) + 1;
                return acc;
            }, {});
            
            const priorityChartData = Object.entries(priorityCounts)
                .map(([name, value]) => ({ 
                    name, 
                    value, 
                    priority: parseInt(name.slice(1))
                }))
                .sort((a, b) => b.priority - a.priority);

            updatePriorityPieChart(priorityChartData);
        }

        function updatePriorityPieChart(data) {
            if (priorityChartInstance) {
                priorityChartInstance.destroy();
            }
            
            if (data.length === 0) {
                priorityChartContainer.innerHTML = '<p class="text-center text-gray-500 p-4">No priority data to display.</p>';
                return;
            } else {
                if (!priorityChartContainer.querySelector('canvas')) {
                    priorityChartContainer.innerHTML = '<canvas id="priorityChart"></canvas>';
                }
            }

            const ctx = document.getElementById('priorityChart').getContext('2d');
            
            const chartData = {
                labels: data.map(d => d.name),
                datasets: [{
                    data: data.map(d => d.value),
                    backgroundColor: data.map(d => {
                        return PRIORITY_COLORS[d.priority] ? PRIORITY_COLORS[d.priority].hex : PRIORITY_COLORS['Other'].hex;
                    }),
                    borderColor: '#ffffff',
                    borderWidth: 3
                }]
            };

            priorityChartInstance = new Chart(ctx, {
                type: 'doughnut',
                data: chartData,
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    cutout: '60%',
                    plugins: {
                        legend: {
                            position: 'right',
                            labels: {
                                font: {
                                    family: "'Inter', sans-serif",
                                    size: 13,
                                    weight: '600'
                                },
                                boxWidth: 14,
                                padding: 18,
                                usePointStyle: true,
                                pointStyle: 'circle'
                            }
                        },
                        tooltip: {
                            backgroundColor: 'rgba(0, 0, 0, 0.8)',
                            padding: 12,
                            titleFont: {
                                family: "'Inter', sans-serif",
                                size: 14,
                                weight: 'bold'
                            },
                            bodyFont: {
                                family: "'Inter', sans-serif",
                                size: 13
                            },
                            callbacks: {
                                label: function(context) {
                                    let label = context.label || '';
                                    if (label) {
                                        label += ': ';
                                    }
                                    if (context.parsed !== null) {
                                        label += context.parsed + ' issues';
                                    }
                                    return label;
                                }
                            }
                        }
                    },
                    animation: {
                        animateRotate: true,
                        animateScale: true,
                        duration: 1000,
                        easing: 'easeInOutQuart'
                    }
                }
            });
        }

        function generateBarChartHTML(data) {
            if (data.length === 0) {
                return '<p class="text-center text-gray-500 p-4">No data to display.</p>';
            }
            const maxValue = Math.max(...data.map(d => d.value));
            return data.map(item => `
                <div class="flex items-center space-x-3 group">
                    <span class="text-sm font-semibold w-36 text-gray-700 truncate transition-colors group-hover:text-gray-900" title="${item.name}">${item.name}</span>
                    <div class="flex-grow bg-gray-100 rounded-full h-5 overflow-hidden shadow-inner">
                        <div class="chart-bar h-full rounded-full flex items-center justify-end pr-3 text-xs font-bold text-white shadow-md"
                             style="width: 0%; background: linear-gradient(90deg, ${item.color}, ${item.color}dd); min-width: 10%;"
                             data-width="${maxValue > 0 ? (item.value / maxValue) * 100 : 0}">
                             ${item.value}
                        </div>
                    </div>
                </div>
            `).join('');
        }

        function animateChartBars() {
            setTimeout(() => {
                document.querySelectorAll('.chart-bar').forEach(bar => {
                    const width = bar.getAttribute('data-width');
                    bar.style.width = width + '%';
                });
            }, 100);
        }

        function getRadiusByPriority(priority) {
            switch (priority) {
                case 5: return 13; // Was 12
                case 4: return 11; // Was 10
                case 3: return 9;  // Was 8
                case 2: return 7;  // Was 6
                case 1: return 6;  // Was 5
                default: return 7; // Was 6
            }
        }

        function updateMap(data) {
            if (!mapInstance || !markersLayer) {
                console.error("Map or markers layer not initialized.");
                return;
            }
            
            markersLayer.clearLayers();

            if (data.length === 0) {
                return;
            }

            data.forEach(issue => {
                if (issue.Lat != null && issue.Lon != null) {
                    
                    let color;
                    if (mapColorMode === 'utility') {
                        color = UTILITY_COLORS[issue.Utility]?.hex || UTILITY_COLORS['Other'].hex;
                    } else {
                        const p = issue.Priority || 0;
                        color = PRIORITY_COLORS[p] ? PRIORITY_COLORS[p].hex : PRIORITY_COLORS['Other'].hex;
                    }

                    const marker = L.circleMarker([issue.Lat, issue.Lon], {
                        radius: getRadiusByPriority(issue.Priority),
                        color: color, // Was '#ffffff'
                        weight: 3,
                        fillColor: color,
                        fillOpacity: 0.7, // Was 0.8
                        className: 'marker-pulse'
                    }).addTo(markersLayer);

                    marker.on('click', () => showModal(issue));
                }
            });
            
            // Keep map zoomed out on mobile
            if (window.innerWidth <= 768) {
                mapInstance.setView([52.1, -9.5], 8);
            } else if (markersLayer.getLayers().length > 0) {
                mapInstance.fitBounds(markersLayer.getBounds().pad(0.1));
            }
        }

        function showModal(issue) {
            const color = UTILITY_COLORS[issue.Utility] || UTILITY_COLORS['Other'];
            const statusColor = issue.Status === 'Ongoing' ? 'text-red-600' : 'text-green-600';
            const p = issue.Priority || 0;
            const priorityBadge = `<span class="priority-badge bg-${p === 5 ? 'red' : p >= 3 ? 'orange' : p >= 1 ? 'yellow' : 'gray'}-100 text-${p === 5 ? 'red' : p >= 3 ? 'orange' : p >= 1 ? 'yellow' : 'gray'}-800">P${p}</span>`;

            modalContentEl.innerHTML = `
                <div class="p-4 sm:p-5 rounded-t-2xl text-white flex justify-between items-center" style="background: linear-gradient(135deg, ${color.hex}, ${color.hex}dd);">
                    <h2 class="text-2xl font-bold truncate pr-4">${issue.Facility}</h2>
                    <button id="closeModalButton" class="text-white hover:bg-white hover:bg-opacity-20 rounded-full p-2 transition">
                        <svg xmlns="http://www.w3.org/2000/svg" class="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                </div>
                <div class="p-4 sm:p-7 space-y-5">
                    <div class="grid grid-cols-2 gap-5">
                        <div class="bg-gray-50 p-4 rounded-xl border border-gray-200">
                            <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Utility Affected</p>
                            <p class="text-lg font-bold ${color.text}">${issue.Utility}</p>
                        </div>
                        <div class="bg-gray-50 p-4 rounded-xl border border-gray-200">
                            <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Status / Priority</p>
                            <p class="text-lg font-bold ${statusColor} flex items-center">${issue.Status} ${priorityBadge}</p>
                        </div>
                    </div>
                    <div class="pt-2">
                        <p class="text-xs font-bold text-gray-500 uppercase tracking-wider mb-2">Issue Description</p>
                        <div class="bg-gradient-to-br from-gray-50 to-gray-100 p-4 rounded-xl border border-gray-200 max-h-40 overflow-y-auto shadow-inner">
                            <p class="text-gray-800 text-base leading-relaxed">${issue.Description}</p>
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-5 border-t-2 border-gray-100 pt-5">
                        <div class="bg-blue-50 p-4 rounded-xl border border-blue-100">
                            <p class="text-xs font-bold text-blue-600 uppercase tracking-wider mb-2">Reported By</p>
                            <p class="text-gray-900 font-semibold">${issue.FirstName} ${issue.LastName}</p>
                            <p class="text-sm text-gray-600 mt-1">${issue.Email}</p>
                        </div>
                        <div class="bg-purple-50 p-4 rounded-xl border border-purple-100">
                            <p class="text-xs font-bold text-purple-600 uppercase tracking-wider mb-2">Time & Location</p>
                            <p class="text-gray-900 font-semibold">${issue.Date}</p>
                            <p class="text-sm text-gray-600 mt-1">${issue.Location || 'N/A'}</p>
                        </div>
                    </div>
                </div>
            `;
            modalEl.classList.remove('hidden');

            document.getElementById('closeModalButton').addEventListener('click', hideModal);
        }

        function hideModal() {
            modalEl.classList.add('hidden');
            modalContentEl.innerHTML = '';
        }

        function getWeatherDescription(code) {
            const descriptions = {
                0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast',
                45: 'Fog', 48: 'Freezing fog',
                51: 'Light drizzle', 53: 'Drizzle', 55: 'Intense drizzle',
                61: 'Slight rain', 63: 'Rain', 65: 'Heavy rain',
                80: 'Slight showers', 81: 'Showers', 82: 'Violent showers',
                95: 'Thunderstorm', 96: 'Thunderstorm + hail', 99: 'Thunderstorm + heavy hail'
            };
            return descriptions[code] || 'Weather code ' + code;
        }

        function loadSafetyAlerts() {
            const tickerEl = document.getElementById('safetyAlertsTicker');
            
            try {
                if (!PRELOADED_WEATHER_DATA || !PRELOADED_WEATHER_DATA.alertsCork || !PRELOADED_WEATHER_DATA.alertsKerry) {
                    tickerEl.style.display = 'none';
                    return;
                }

                const { alertsCork, alertsKerry } = PRELOADED_WEATHER_DATA;
                const allAlerts = [];

                if (alertsCork.alerts && alertsCork.alerts.length > 0) {
                    alertsCork.alerts.forEach(alert => {
                        allAlerts.push({
                            location: 'CORK',
                            headline: alert.headline || alert.event || 'Weather Alert',
                            severity: alert.severity || 'Moderate'
                        });
                    });
                }

                if (alertsKerry.alerts && alertsKerry.alerts.length > 0) {
                    alertsKerry.alerts.forEach(alert => {
                        allAlerts.push({
                            location: 'KERRY',
                            headline: alert.headline || alert.event || 'Weather Alert',
                            severity: alert.severity || 'Moderate'
                        });
                    });
                }

                if (allAlerts.length === 0) {
                    tickerEl.innerHTML = `
                        <div class="bg-gradient-to-r from-green-50 to-emerald-50 border-2 border-green-300 p-4 flex items-center rounded-2xl shadow-lg">
                            <svg class="w-7 h-7 text-green-600 mr-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                            <span class="font-bold text-green-800 text-base">✓ NO ACTIVE WEATHER WARNINGS</span>
                            <span class="ml-4 text-green-600 text-sm">All regions clear - Normal operations</span>
                        </div>
                    `;
                    return;
                }

                const tickerContent = allAlerts.map(alert => {
                    const severityColor = alert.severity === 'Severe' || alert.severity === 'Extreme' ? 'text-red-700' : 'text-orange-700';
                    return `
                        <span class="inline-flex items-center mx-8">
                            <svg class="w-5 h-5 text-red-600 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>
                            <span class="font-bold ${severityColor}">${alert.location}:</span>
                            <span class="ml-2 text-gray-800">${alert.headline}</span>
                        </span>
                    `;
                }).join('');

                tickerEl.innerHTML = `
                    <div class="ticker-wrap p-4 rounded-2xl shadow-lg">
                        <div class="flex items-center">
                            <span class="bg-red-600 text-white px-4 py-2 rounded-lg font-bold text-sm mr-4 flex-shrink-0 shadow-md">⚠ ALERT</span>
                            <div class="ticker font-semibold text-sm">
                                ${tickerContent}${tickerContent}
                            </div>
                        </div>
                    </div>
                `;
            } catch (error) {
                console.error("Safety Alerts Error:", error);
                tickerEl.style.display = 'none';
            }
        }

        // --- REMOVED findHighTides function ---

        function loadWeatherData() {
            try {
                if (!PRELOADED_WEATHER_DATA || !PRELOADED_TIDE_DATA) {
                    throw new Error('Preloaded weather or tide data is missing or invalid.');
                }

                const { forecasts, alertsCork, alertsKerry } = PRELOADED_WEATHER_DATA;
                const tides = PRELOADED_TIDE_DATA;
                
                if (!forecasts || forecasts.length < 2 || !tides) {
                     throw new Error('Forecast or tide data is incomplete.');
                }

                const [cork, kerry] = forecasts; 
                // Tides object is now different: e.g., tides['Cork'] and tides['Kerry (Fenit)']

                let summaryHtml = '<div class="grid grid-cols-1 sm:grid-cols-2 gap-4 flex-grow">';
                summaryHtml += `
                    <div class="text-center bg-gradient-to-br from-blue-50 to-cyan-50 p-4 rounded-xl border-2 border-blue-200 shadow-md">
                        <strong class="text-base font-bold text-gray-900 uppercase tracking-wide">Cork (Current):</strong> 
                        <span class="ml-2 text-3xl font-black text-blue-600">${cork.current.temperature_2m}°C</span>
                    </div>
                    <div class="text-center bg-gradient-to-br from-blue-50 to-cyan-50 p-4 rounded-xl border-2 border-blue-200 shadow-md">
                        <strong class="text-base font-bold text-gray-900 uppercase tracking-wide">Kerry (Current):</strong> 
                        <span class="ml-2 text-3xl font-black text-blue-600">${kerry.current.temperature_2m}°C</span>
                    </div>
                `;
                summaryHtml += '</div>';

                let detailHtml = '<div class="grid grid-cols-1 md:grid-cols-3 gap-6">';

                // --- Weather Column ---
                detailHtml += '<div class="space-y-3">';
                detailHtml += '<h4 class="text-base font-bold text-gray-800 border-b-2 border-blue-300 pb-2 mb-3 flex items-center"><svg class="w-5 h-5 mr-2 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 10-9.78 2.096A4.001 4.001 0 003 15z"/></svg>3-Day Weather Forecast</h4>';
                
                const today = new Date();
                const dayLabels = ['Today', 'Tomorrow', (new Date(new Date().setDate(new Date().getDate() + 2))).toLocaleDateString('en-IE', { weekday: 'short' })];


                for (let i = 0; i < 3; i++) {
                    // Safety check for daily data
                    if (!cork.daily || !cork.daily.time || !cork.daily.time[i] || !cork.daily.weathercode || !cork.daily.weathercode[i]) {
                        console.warn("Weather data missing for day " + i);
                        continue;
                    }
                    
                    const date = cork.daily.time[i].slice(5);
                    const corkWeather = getWeatherDescription(cork.daily.weathercode[i]);
                    const kerryWeather = getWeatherDescription(kerry.daily.weathercode[i]);

                    detailHtml += `
                        <div class="bg-gradient-to-br from-gray-50 to-gray-100 border-2 border-gray-200 p-4 rounded-xl shadow-md hover:shadow-lg transition-shadow">
                            <strong class="text-gray-900 font-bold text-base">${dayLabels[i]} (${date})</strong>
                            <div class="text-xs mt-2 space-y-2">
                                <div class="bg-white p-2 rounded-lg">
                                    <strong class="text-blue-600">Cork:</strong> ${cork.daily.temperature_2m_min[i]}° / ${cork.daily.temperature_2m_max[i]}°C | 
                                    <strong>Wind:</strong> ${cork.daily.wind_speed_10m_max[i]} km/h | 
                                    <strong>Sky:</strong> ${corkWeather}
                                </div>
                                <div class="bg-white p-2 rounded-lg">
                                    <strong class="text-blue-600">Kerry:</strong> ${kerry.daily.temperature_2m_min[i]}° / ${kerry.daily.temperature_2m_max[i]}°C | 
                                    <strong>Wind:</strong> ${kerry.daily.wind_speed_10m_max[i]} km/h | 
                                    <strong>Sky:</strong> ${kerryWeather}
                                </div>
                            </div>
                        </div>
                    `;
                }
                detailHtml += '</div>';

                // --- Tides Column (MODIFIED) ---
                const corkTides = tides.Cork || {};
                const kerryTides = tides["Kerry (Fenit)"] || {};
                const corkDayKeys = Object.keys(corkTides);
                const kerryDayKeys = Object.keys(kerryTides);
                
                detailHtml += '<div class="space-y-3">';
                detailHtml += '<h4 class="text-base font-bold text-gray-800 border-b-2 border-cyan-300 pb-2 mb-3 flex items-center"><svg class="w-5 h-5 mr-2 text-cyan-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/></svg>3-Day High/Low Tides</h4>';

                for (let i = 0; i < 3; i++) {
                    const dayLabel = corkDayKeys[i] || kerryDayKeys[i] || dayLabels[i] || "Day " + (i+1);
                    
                    const corkTideHtml = corkTides[dayLabel] || '<span class="data-unavailable">Data unavailable</span>';
                    const kerryTideHtml = kerryTides[dayLabel] || '<span class="data-unavailable">Data unavailable</span>';

                    detailHtml += `
                        <div class="bg-gradient-to-br from-cyan-50 to-blue-50 border-2 border-cyan-200 p-4 rounded-xl shadow-md hover:shadow-lg transition-shadow">
                            <strong class="text-gray-900 font-bold text-base">${dayLabel}</strong>
                            <div class="text-xs mt-2 space-y-2">
                                <!-- The 'break-words' and 'innerHTML' are key for rendering the bold tags -->
                                <div class="bg-white p-2 rounded-lg break-words" id="cork-tide-${i}"></div>
                                <div class="bg-white p-2 rounded-lg break-words" id="kerry-tide-${i}"></div>
                            </div>
                        </div>
                    `;

                    // We must inject the HTML this way to render the <b> tags
                    // We'll do it safely right after creating the elements
                    setTimeout(() => {
                        const corkEl = document.getElementById(`cork-tide-${i}`);
                        const kerryEl = document.getElementById(`kerry-tide-${i}`);
                        if(corkEl) corkEl.innerHTML = `<strong class="text-cyan-600">Cork:</strong> ${corkTideHtml}`;
                        if(kerryEl) kerryEl.innerHTML = `<strong class="text-cyan-600">Kerry (Fenit):</strong> ${kerryTideHtml}`;
                    }, 0);
                }
                detailHtml += '</div>';

                // --- Warnings Column ---
                const corkWarnings = alertsCork.alerts?.map(a => `<li class="flex items-start"><svg class="w-4 h-4 text-red-600 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg><span><strong class="text-red-700">Cork:</strong> ${a.headline}</span></li>`).join('') || '';
                const kerryWarnings = alertsKerry.alerts?.map(a => `<li class="flex items-start"><svg class="w-4 h-4 text-red-600 mr-2 mt-0.5 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg><span><strong class="text-red-700">Kerry:</strong> ${a.headline}</span></li>`).join('') || '';
                
                detailHtml += '<div class="space-y-3">';
                detailHtml += '<h4 class="text-base font-bold text-gray-800 border-b-2 border-red-300 pb-2 mb-3 flex items-center"><svg class="w-5 h-5 mr-2 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>Active Met Éireann Warnings</h4>';
                detailHtml += '<div class="bg-gradient-to-br from-red-50 to-orange-50 border-2 border-red-200 p-4 rounded-xl shadow-md">';
                
                if (corkWarnings.length > 0 || kerryWarnings.length > 0) {
                    detailHtml += '<ul class="space-y-2 text-sm text-gray-800">';
                    detailHtml += corkWarnings;
                    detailHtml += kerryWarnings;
                    detailHtml += '</ul>';
                } else {
                    detailHtml += '<p class="text-sm text-green-700 font-semibold flex items-center"><svg class="w-4 h-4 mr-2" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clip-rule="evenodd"/></svg>No active warnings for Cork or Kerry.</p>';
                }
                detailHtml += '</div></div>'; // close warnings box and space-y-3
                
                detailHtml += '</div>'; // close grid

                // --- Combine and Inject HTML ---
                weatherCardContent.innerHTML = `
                    <div id="weatherClickTarget" class="cursor-pointer group">
                        <div class="flex justify-between items-center">
                            ${summaryHtml}
                            <div class="ml-4 flex-shrink-0">
                                <svg id="weatherChevron" class="w-8 h-8 text-gray-400 group-hover:text-blue-600 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                            </div>
                        </div>
                        <div id="weatherDetails" class="hidden mt-6 pt-6 border-t-2 border-gray-200">
                            ${detailHtml}
                        </div>
                    </div>
                `;

                // Add event listener for the new weather toggle
                const weatherClickTarget = document.getElementById('weatherClickTarget');
                const weatherDetails = document.getElementById('weatherDetails');
                const weatherChevron = document.getElementById('weatherChevron');
                
                if (weatherClickTarget) {
                    weatherClickTarget.addEventListener('click', () => {
                        weatherDetails.classList.toggle('hidden');
                        weatherChevron.classList.toggle('rotate-180');
                    });
                }

            } catch (error) {
                console.error("Weather Data Error:", error);
                weatherCardContent.innerHTML = `<p class="text-red-600 font-semibold p-4">Error loading weather data: ${error.message}</p>`;
            }
        }

        function initMap() {
            try {
                mapInstance = L.map('map').setView([52.1, -9.5], 8); // <-- Widened view and zoomed out to 8
                L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                    attribution: '© OpenStreetMap contributors, © CARTO',
                    maxZoom: 19
                }).addTo(mapInstance);
                markersLayer = L.featureGroup().addTo(mapInstance);
                document.getElementById('map').classList.remove('loading-shimmer');
            } catch (e) {
                console.error("Map init error:", e);
                document.getElementById('map').innerHTML = '<p class="text-red-600 font-semibold p-4">Error loading map. Please refresh.</p>';
            }
        }

        // --- Init & Event Listeners ---
        document.addEventListener('DOMContentLoaded', () => {
            // --- 1. Assign DOM Elements ---
            toggleButton = document.getElementById('toggleButton');
            mapToggle = document.getElementById('mapToggle');
            totalCard = document.getElementById('totalCard');
            ongoingCard = document.getElementById('ongoingCard');
            completeCard = document.getElementById('completeCard');
            utilityChartEl = document.getElementById('utilityChart');
            priorityChartContainer = document.getElementById('priorityChartContainer');
            priorityChartEl = document.getElementById('priorityChart');
            modalEl = document.getElementById('modal');
            modalContentEl = document.getElementById('modalContent');
            weatherCardContent = document.getElementById('weatherCardContent');

            // --- 2. Check if elements exist before proceeding ---
            if (!toggleButton || !mapToggle || !utilityChartEl || !priorityChartContainer || !modalEl || !weatherCardContent) {
                console.error("Critical DOM elements are missing. Dashboard cannot initialize.");
                return; // Stop if essential elements are missing
            }
            
            // --- 3. Initialize Dashboard ---
            initMap();
            loadSafetyAlerts();
            loadWeatherData();
            updateDashboard();
            
            // --- Set initial button text based on default state ---
            toggleButton.textContent = showComplete ? 'Ongoing Only' : 'Show All';

            // --- 4. Attach Event Listeners ---
            toggleButton.addEventListener('click', () => {
                showComplete = !showComplete;
                toggleButton.textContent = showComplete ? 'Ongoing Only' : 'Show All';
                toggleButton.classList.toggle('bg-red-600', !showComplete);
                toggleButton.classList.toggle('hover:bg-red-700', !showComplete);
                toggleButton.classList.toggle('bg-gray-600', showComplete);
                toggleButton.classList.toggle('hover:bg-gray-700', showComplete);
                updateDashboard();
            });
            
            mapToggle.addEventListener('click', () => {
                mapColorMode = mapColorMode === 'utility' ? 'priority' : 'utility';
                mapToggle.textContent = mapColorMode === 'utility' ? 'By Utility' : 'By Priority';
                mapToggle.classList.toggle('bg-blue-600', mapColorMode === 'utility');
                mapToggle.classList.toggle('hover:bg-blue-700', mapColorMode === 'utility');
                mapToggle.classList.toggle('bg-orange-600', mapColorMode === 'priority');
                mapToggle.classList.toggle('hover:bg-orange-700', mapColorMode === 'priority');
                
                // We only need to update the map, not the whole dashboard
                const filteredData = RAW_DATA.filter(issue => showComplete || issue.Status === 'Ongoing');
                updateMap(filteredData);
            });

            modalEl.addEventListener('click', (e) => {
                if (e.target === modalEl) {
                    hideModal();
                }
            });

            // --- 5. Start Live Clock ---
            function getOrdinal(n) {
                const s = ["th", "st", "nd", "rd"];
                const v = n % 100;
                return n + (s[(v - 20) % 10] || s[v] || s[0]);
            }

            function updateLiveClock() {
                const now = new Date();
                const day = now.toLocaleDateString('en-IE', { weekday: 'long' });
                const date = getOrdinal(now.getDate());
                const month = now.toLocaleDateString('en-IE', { month: 'long' });
                const year = now.getFullYear();
                const timeString = now.toLocaleTimeString('en-IE', { hour: '2-digit', minute: '2-digit' });
                
                const clockEl = document.getElementById('live-clock');
                if (clockEl) {
                    clockEl.innerHTML = `${day} the ${date} of ${month} ${year} | ${timeString}`;
                }
            }
            updateLiveClock(); // Run once immediately
            setInterval(updateLiveClock, 1000); // Update clock every second
        });
    </script>
</body>
</html>
"""

# --- 3. STREAMLIT APP LOGIC ---

def main():
    st.set_page_config(
        layout="wide", 
        page_title="HSE Dashboard", 
        page_icon="https://www.hse.ie/favicon-32x32.png"
    )

    # Fetch data
    weather_data = fetch_all_weather()
    tide_data = fetch_scraped_tides() # <-- Decoupled fetch
    jotform_data_json = fetch_jotform_data()
    
    # Convert data to JSON string for injection
    weather_data_json = json.dumps(weather_data)
    tide_data_json = json.dumps(tide_data)

    # Replace the placeholders in the HTML template
    html_content = HTML_TEMPLATE.replace("%%WEATHER_DATA_PLACEHOLDER%%", weather_data_json)
    html_content = html_content.replace("%%TIDE_DATA_PLACEHOLDER%%", tide_data_json)
    html_content = html_content.replace("%%JOTFORM_DATA_PLACEHOLDER%%", jotform_data_json)

    # Render the HTML in Streamlit
    st.components.v1.html(html_content, height=1800, scrolling=True)

if __name__ == "__main__":
    main()

